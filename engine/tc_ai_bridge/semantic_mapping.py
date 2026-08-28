"""Bridge Stage 3: source-semantic-unit -> target-passage mapping.

The module is target-language agnostic. It consumes a canonical original-language
resource database, a target USFM passage index, and any Structured-Output model
client implementing ``_post_structured(instructions, input_text, name, schema)``
(the existing Bridge OpenAIResponsesClient already has that method).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Protocol, Sequence

from .usfm_passages import PassageWindow, TargetSegment, UsfmPassageIndex

SCHEMA_VERSION = "bridge.semantic_mapping_result.v0.3"
ENGINE_VERSION = "3.0.0-beta14-stage3"

RELATIONSHIPS = (
    "SAME_VERSE", "REORDERED_WITHIN_VERSE", "CROSS_VERSE_MOVED",
    "CROSS_VERSE_REORDERED", "SPLIT_ACROSS_VERSES", "MERGED_ACROSS_VERSES",
    "CLAUSE_MOVED", "CLAUSE_REORDERED", "SENTENCE_MOVED", "SENTENCE_REORDERED",
    "PARAPHRASED", "PRONOMINALIZED", "GRAMMATICALLY_ENCODED", "IMPLICIT",
    "VERSIFICATION_DIFFERENCE", "UNCERTAIN",
)
MEANING_STATUSES = ("PRESERVED", "PARTIALLY_PRESERVED", "NOT_LOCATED", "POSSIBLE_PROBLEM", "UNCERTAIN")


class SemanticMappingError(RuntimeError):
    pass


class SemanticMappingValidationError(SemanticMappingError):
    pass


class StructuredClient(Protocol):
    model: str
    def _post_structured(self, instructions: str, input_text: str, schema_name: str, schema: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SourceToken:
    id: str
    reference: str
    ordinal: int
    text: str
    occurrence: int
    lemma: str
    strong: str
    morph: str
    ult_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceSemanticUnit:
    id: str
    tool: str
    check_id: str
    group_id: str
    source_reference: str
    source_quote: str
    source_token_ids: tuple[str, ...]
    note: str = ""
    occurrence: int = 1


@dataclass(frozen=True)
class MappingRun:
    source_units: tuple[SourceSemanticUnit, ...]
    searched_windows: tuple[str, ...]
    result: dict[str, Any]
    fingerprint: str
    cache_hit: bool = False


class SemanticSourceRepository:
    """Read-only indexed original-language evidence compiled from Stage 2."""

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        if not self.path.exists():
            raise SemanticMappingError(f"Semantic source database not found: {self.path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def metadata(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM metadata").fetchall()
        return {r["key"]: json.loads(r["value_json"]) for r in rows}

    def tokens_for_reference(self, reference: str) -> list[SourceToken]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM source_tokens WHERE reference=? ORDER BY ordinal", (reference,)
            ).fetchall()
        return [SourceToken(
            id=r["id"], reference=r["reference"], ordinal=r["ordinal"], text=r["text"],
            occurrence=r["occurrence"], lemma=r["lemma"], strong=r["strong"], morph=r["morph"],
            ult_words=tuple(json.loads(r["ult_words_json"] or "[]")),
        ) for r in rows]

    def verse(self, reference: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            r = conn.execute("SELECT * FROM source_verses WHERE reference=?", (reference,)).fetchone()
        if not r:
            return None
        return {"reference": r["reference"], "source_text": r["source_text"], "ult_text": r["ult_text"]}

    def tokens_by_ids(self, token_ids: Sequence[str]) -> list[SourceToken]:
        """Fetch canonical tokens in caller-supplied order."""
        ids = [str(x) for x in token_ids if str(x)]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM source_tokens WHERE id IN ({placeholders})", tuple(ids)
            ).fetchall()
        by_id = {r["id"]: r for r in rows}
        out: list[SourceToken] = []
        for token_id in ids:
            r = by_id.get(token_id)
            if r is None:
                continue
            out.append(SourceToken(
                id=r["id"], reference=r["reference"], ordinal=r["ordinal"], text=r["text"],
                occurrence=r["occurrence"], lemma=r["lemma"], strong=r["strong"], morph=r["morph"],
                ult_words=tuple(json.loads(r["ult_words_json"] or "[]")),
            ))
        return out

    def unit_for_check(
        self, *, book: str, chapter: str | int, verse: str | int,
        tool: str, check_id: str = "", group_id: str = "", source_quote: str = "",
        occurrence: int = 1,
    ) -> SourceSemanticUnit:
        reference = f"{book.upper()} {chapter}:{verse}"
        with self._connect() as conn:
            row = None
            if check_id:
                row = conn.execute(
                    "SELECT * FROM help_anchors WHERE book=? AND id=? LIMIT 1",
                    (book.upper(), check_id),
                ).fetchone()
            if row is None and group_id:
                rows = conn.execute(
                    "SELECT * FROM help_anchors WHERE reference=? AND tool=? AND group_id=? ORDER BY id",
                    (reference, tool, group_id),
                ).fetchall()
                if source_quote:
                    norm = _norm_quote(source_quote)
                    row = next((r for r in rows if _norm_quote(r["quote"]) == norm), None)
                row = row or (rows[0] if rows else None)
            if row is None and source_quote:
                rows = conn.execute(
                    "SELECT * FROM help_anchors WHERE reference=? AND tool=? ORDER BY id",
                    (reference, tool),
                ).fetchall()
                norm = _norm_quote(source_quote)
                row = next((r for r in rows if _norm_quote(r["quote"]) == norm), None)

        if row is not None:
            token_ids = tuple(json.loads(row["token_ids_json"] or "[]"))
            if not token_ids:
                token_ids = tuple(t.id for t in self._resolve_quote_tokens(reference, row["quote"], int(row["occurrence"] or 1)))
            return SourceSemanticUnit(
                id=f"{tool}:{row['id']}", tool=tool, check_id=str(row["id"]), group_id=str(row["group_id"] or ""),
                source_reference=str(row["reference"]), source_quote=str(row["quote"] or source_quote),
                source_token_ids=token_ids, note=str(row["note"] or ""), occurrence=int(row["occurrence"] or 1),
            )

        if not source_quote:
            raise SemanticMappingError(f"Cannot resolve semantic unit for {reference} {tool}/{check_id or group_id}: no canonical quote")
        toks = self._resolve_quote_tokens(reference, source_quote, occurrence)
        if not toks:
            raise SemanticMappingError(f"Canonical source quote not found in {reference}: {source_quote}")
        identity = hashlib.sha256(f"{reference}\u241f{tool}\u241f{source_quote}\u241f{occurrence}".encode("utf-8")).hexdigest()[:16]
        return SourceSemanticUnit(
            id=f"{tool}:resolved:{identity}", tool=tool, check_id=check_id, group_id=group_id,
            source_reference=reference, source_quote=source_quote,
            source_token_ids=tuple(t.id for t in toks), occurrence=occurrence,
        )

    def reference_unit(self, reference: str) -> SourceSemanticUnit:
        toks = self.tokens_for_reference(reference)
        if not toks:
            raise SemanticMappingError(f"Canonical source reference not found: {reference}")
        return SourceSemanticUnit(
            id=f"source-reference:{reference}", tool="sourceReference", check_id="", group_id="",
            source_reference=reference, source_quote=" ".join(t.text for t in toks),
            source_token_ids=tuple(t.id for t in toks),
        )

    def _resolve_quote_tokens(self, reference: str, quote: str, occurrence: int) -> list[SourceToken]:
        tokens = self.tokens_for_reference(reference)
        words = [w for w in _norm_quote(quote).split(" ") if w]
        if not words:
            return []
        hay = [_norm_quote(t.text) for t in tokens]
        matches: list[list[SourceToken]] = []
        for i in range(0, len(hay) - len(words) + 1):
            if hay[i:i+len(words)] == words:
                matches.append(tokens[i:i+len(words)])
        idx = max(1, int(occurrence or 1)) - 1
        return matches[idx] if idx < len(matches) else []


def _norm_quote(value: str) -> str:
    import unicodedata, re
    s = unicodedata.normalize("NFC", str(value or ""))
    s = re.sub(r"[\s\u200b\u200c\u200d]+", " ", s).strip()
    # Keep letters/marks/digits, turn source punctuation into spaces.
    chars = []
    for ch in s:
        cat = unicodedata.category(ch)
        chars.append(ch if cat[0] in {"L", "M", "N"} else " ")
    return " ".join("".join(chars).split()).casefold()


def semantic_mapping_schema() -> dict[str, Any]:
    span = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "reference": {"type": "string"}, "quote": {"type": "string"},
            "start": {"type": ["integer", "null"]}, "end": {"type": ["integer", "null"]},
        },
        "required": ["reference", "quote", "start", "end"],
    }
    mapping = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "source_unit_id": {"type": "string"},
            "source_token_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "source_reference": {"type": "string"},
            "target_spans": {"type": "array", "items": span},
            "relationships": {"type": "array", "items": {"type": "string", "enum": list(RELATIONSHIPS)}, "minItems": 1},
            "meaning_status": {"type": "string", "enum": list(MEANING_STATUSES)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {
                "type": "object", "additionalProperties": False,
                "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "explanation": {"type": "string"}},
                "required": ["source", "target", "explanation"],
            },
        },
        "required": ["source_unit_id", "source_token_ids", "source_reference", "target_spans", "relationships", "meaning_status", "confidence", "evidence"],
    }
    unresolved = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "source_unit_id": {"type": "string"},
            "reason": {"type": "string", "enum": ["NOT_LOCATED", "AMBIGUOUS", "MODEL_UNCERTAIN", "SEARCH_BUDGET_EXHAUSTED"]},
            "detail": {"type": "string"},
        },
        "required": ["source_unit_id", "reason", "detail"],
    }
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "mappings": {"type": "array", "items": mapping},
            "unresolved_source_units": {"type": "array", "items": unresolved},
            "passage_assessment": {"type": "string", "enum": ["MAPPED", "NEEDS_REVIEW", "POSSIBLE_PROBLEM"]},
        },
        "required": ["mappings", "unresolved_source_units", "passage_assessment"],
    }


class SemanticMappingStore:
    """Crash-safe companion persistence. Never writes target USFM/tC checkData."""
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path_for(self, book: str, fingerprint: str) -> Path:
        return self.root / "semanticMappings" / book.lower() / f"{fingerprint}.json"

    def load(self, book: str, fingerprint: str) -> dict[str, Any] | None:
        path = self.path_for(book, fingerprint)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def save(self, book: str, fingerprint: str, payload: dict[str, Any]) -> Path:
        path = self.path_for(book, fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # Validate the exact bytes before replacement.
        json.loads(tmp.read_text(encoding="utf-8"))
        tmp.replace(path)
        return path

    def confirm(
        self, *, book: str, fingerprint: str, source_unit_id: str,
        decision: str, reviewer: str = "", note: str = "",
        edited_mapping: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a human mapping decision without touching USFM/tC checkData.

        ``decision`` is one of confirmed/rejected/edited/unsure.  Edited mappings
        are stored as human data alongside the AI proposal; callers must validate
        any edited target spans against the current USFM before passing them here.
        """
        decision = str(decision or "").strip().lower()
        if decision not in {"confirmed", "rejected", "edited", "unsure"}:
            raise SemanticMappingError(f"Invalid semantic mapping decision: {decision}")
        payload = self.load(book, fingerprint)
        if payload is None:
            raise SemanticMappingError(f"Semantic mapping record not found: {book}/{fingerprint}")
        known = {str(x.get("id") or "") for x in payload.get("sourceUnits", []) if isinstance(x, dict)}
        if source_unit_id not in known:
            raise SemanticMappingError(f"Unknown source semantic unit in mapping record: {source_unit_id}")
        if edited_mapping is not None and decision != "edited":
            raise SemanticMappingError("edited_mapping requires decision='edited'")
        now = datetime.now(timezone.utc).isoformat()
        event = {
            "sourceUnitId": source_unit_id, "decision": decision,
            "reviewer": str(reviewer or ""), "note": str(note or ""), "at": now,
        }
        if edited_mapping is not None:
            event["editedMapping"] = edited_mapping
        audit = payload.setdefault("reviewAudit", [])
        if not isinstance(audit, list):
            audit = payload["reviewAudit"] = []
        audit.append(event)
        confirmations = payload.setdefault("humanConfirmations", {})
        if not isinstance(confirmations, dict):
            confirmations = payload["humanConfirmations"] = {}
        confirmations[source_unit_id] = event
        provenance = payload.setdefault("provenance", {})
        if isinstance(provenance, dict):
            provenance["lastHumanReviewAt"] = now
        self.save(book, fingerprint, payload)
        return event

    def records_for_reference(self, book: str, source_reference: str) -> list[dict[str, Any]]:
        """Return cached records containing a source unit at ``source_reference``.

        Intended for UI/debug endpoints.  Normal review execution should retain
        the fingerprint directly and avoid scanning the companion directory.
        """
        root = self.root / "semanticMappings" / str(book).lower()
        if not root.exists():
            return []
        out: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            units = payload.get("sourceUnits", []) if isinstance(payload, dict) else []
            if any(isinstance(u, dict) and str(u.get("source_reference") or "") == source_reference for u in units):
                out.append(payload)
        return out


class SemanticMappingEngine:
    def __init__(
        self, source_repo: SemanticSourceRepository, client: StructuredClient,
        *, model: str | None = None, max_neighbor_windows: int = 2,
    ):
        self.source_repo = source_repo
        self.client = client
        self.model = model or str(getattr(client, "model", ""))
        self.max_neighbor_windows = max(0, int(max_neighbor_windows))

    def map_units(
        self, *, target_index: UsfmPassageIndex, source_units: Sequence[SourceSemanticUnit],
        store: SemanticMappingStore | None = None, force: bool = False,
    ) -> MappingRun:
        if not source_units:
            raise SemanticMappingError("No source semantic units supplied")
        seed = self._seed_window(target_index, source_units)
        if seed is None:
            raise SemanticMappingError("No target passage window can be seeded for requested source unit(s)")

        selected_windows = [seed]
        all_mappings: dict[str, dict[str, Any]] = {}
        pending = {u.id: u for u in source_units}
        last_unresolved: dict[str, dict[str, Any]] = {}

        for radius in range(0, self.max_neighbor_windows + 1):
            if radius:
                selected_windows = target_index.expand(seed, before=radius, after=radius)
            requested = list(pending.values())
            if not requested:
                break
            segments = target_index.segments_for_windows(selected_windows)
            fp = self._fingerprint(requested, segments)
            if store and not force:
                cached = store.load(target_index.book, fp)
                if cached:
                    validated = self._validate_result(cached["result"], requested, segments)
                    return MappingRun(tuple(source_units), tuple(w.id for w in selected_windows), validated, fp, True)

            raw = self.client._post_structured(
                self._instructions(),
                json.dumps(self._input_object(requested, selected_windows, segments), ensure_ascii=False),
                "bridge_semantic_mapping_v03", semantic_mapping_schema(),
            )
            validated = self._validate_result(raw, requested, segments)
            for item in validated["mappings"]:
                all_mappings[item["source_unit_id"]] = item
                pending.pop(item["source_unit_id"], None)
            last_unresolved = {x["source_unit_id"]: x for x in validated["unresolved_source_units"] if x["source_unit_id"] in pending}
            if not pending:
                break

        # Search exhaustion is explicitly NOT an omission verdict.
        unresolved = []
        for uid in pending:
            prior = last_unresolved.get(uid, {})
            unresolved.append({
                "source_unit_id": uid,
                "reason": "SEARCH_BUDGET_EXHAUSTED",
                "detail": str(prior.get("detail") or "Meaning was not securely located within the configured adaptive passage search budget; extend passage review or ask a human reviewer."),
            })
        final = {
            "mappings": [all_mappings[u.id] for u in source_units if u.id in all_mappings],
            "unresolved_source_units": unresolved,
            "passage_assessment": "MAPPED" if not unresolved else "NEEDS_REVIEW",
        }
        segments = target_index.segments_for_windows(selected_windows)
        final_fp = self._fingerprint(source_units, segments)
        final = self._validate_result(final, source_units, segments, allow_search_exhausted=True)
        if store:
            store.save(target_index.book, final_fp, {
                "schema": SCHEMA_VERSION, "engineVersion": ENGINE_VERSION,
                "model": self.model, "createdAt": datetime.now(timezone.utc).isoformat(),
                "fingerprint": final_fp, "searchedWindows": [w.id for w in selected_windows],
                "sourceUnits": [asdict(u) for u in source_units], "result": final,
                "provenance": {"proposal": "ai", "humanConfirmation": None},
            })
        return MappingRun(tuple(source_units), tuple(w.id for w in selected_windows), final, final_fp, False)

    def _seed_window(self, index: UsfmPassageIndex, units: Sequence[SourceSemanticUnit]) -> PassageWindow | None:
        refs = [u.source_reference for u in units]
        for ref in refs:
            try:
                _, cv = ref.split(" ", 1); ch, verse = cv.split(":", 1)
            except ValueError:
                continue
            window = index.window_for_source_reference(ch, verse)
            if window:
                return window
        return None

    def _input_object(self, units: Sequence[SourceSemanticUnit], windows: Sequence[PassageWindow], segments: Sequence[TargetSegment]) -> dict[str, Any]:
        refs = sorted({u.source_reference for u in units})
        source_context = []
        for ref in refs:
            v = self.source_repo.verse(ref)
            if v:
                source_context.append(v)
        unit_rows = []
        for u in units:
            toks = {t.id: t for t in self.source_repo.tokens_for_reference(u.source_reference)}
            unit_rows.append({
                "id": u.id, "tool": u.tool, "check_id": u.check_id, "group_id": u.group_id,
                "source_reference": u.source_reference, "source_quote": u.source_quote,
                "source_tokens": [asdict(toks[tid]) for tid in u.source_token_ids if tid in toks],
                "help_note": u.note, "occurrence": u.occurrence,
            })
        return {
            "contract": {
                "target_language_rule": "Do not assume any language-specific word order or verse-local realization.",
                "verse_boundary_rule": "Verse numbers are anchors, not mandatory semantic boundaries.",
                "authority": "UHB/UGNT source tokens are canonical; ULT/help wording is supporting evidence only.",
            },
            "resource_provenance": self.source_repo.metadata().get("resource_manifest", {}),
            "source_units": unit_rows,
            "source_context": source_context,
            "target_passage": {
                "window_ids": [w.id for w in windows],
                "segments": [{"reference": s.reference, "text": s.text} for s in segments],
            },
        }

    @staticmethod
    def _instructions() -> str:
        return (
            "You are Bridge's language-aware Scripture semantic passage mapper. Map every requested canonical Hebrew/Aramaic/Greek source semantic unit to how that meaning is realized in the supplied target-language passage. "
            "Do not assume source verse N must occur in target verse N. The target may reorder sentences/clauses, split one source unit across verses, merge several source units, use pronouns, paraphrase, encode meaning grammatically, or leave a meaning implicit. "
            "Never judge a translation by similarity to English; ULT/help wording is evidence only and UHB/UGNT source data is authoritative. "
            "For every overt target realization, copy an exact verbatim quote from exactly one supplied target segment and give that segment's reference. Do not normalize, translate, repair, or invent target text. "
            "Use an empty target_spans array only for truly implicit/grammatical realizations or when not securely located. If a unit is not securely located, put it in unresolved_source_units rather than declaring an omission. "
            "Do not use POSSIBLE_OMISSION as a relationship; Bridge decides possible-omission state only after adaptive search and review policy. Return only the strict schema."
        )

    def _fingerprint(self, units: Sequence[SourceSemanticUnit], segments: Sequence[TargetSegment]) -> str:
        meta = self.source_repo.metadata()
        payload = {
            "schema": SCHEMA_VERSION, "engine": ENGINE_VERSION, "model": self.model,
            "resources": meta.get("resource_fingerprint") or meta.get("resource_manifest"),
            "sourceUnits": [asdict(u) for u in units],
            "targetSegments": [{"reference": s.reference, "text": s.text} for s in segments],
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _validate_result(
        self, raw: dict[str, Any], units: Sequence[SourceSemanticUnit], segments: Sequence[TargetSegment],
        *, allow_search_exhausted: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise SemanticMappingValidationError("Semantic mapping output must be an object")
        unit_by_id = {u.id: u for u in units}
        segment_by_ref = {s.reference: s for s in segments}
        mappings = raw.get("mappings")
        unresolved = raw.get("unresolved_source_units")
        assessment = str(raw.get("passage_assessment") or "")
        if not isinstance(mappings, list) or not isinstance(unresolved, list) or assessment not in {"MAPPED", "NEEDS_REVIEW", "POSSIBLE_PROBLEM"}:
            raise SemanticMappingValidationError("Semantic mapping output is missing required top-level fields")

        seen: set[str] = set()
        clean_mappings: list[dict[str, Any]] = []
        for item in mappings:
            if not isinstance(item, dict):
                raise SemanticMappingValidationError("Mapping row must be an object")
            uid = str(item.get("source_unit_id") or "")
            if uid not in unit_by_id:
                raise SemanticMappingValidationError(f"Model returned unknown source unit: {uid}")
            if uid in seen:
                raise SemanticMappingValidationError(f"Model duplicated source unit: {uid}")
            seen.add(uid)
            expected = unit_by_id[uid]
            token_ids = [str(x) for x in item.get("source_token_ids") or []]
            if token_ids != list(expected.source_token_ids):
                raise SemanticMappingValidationError(f"Model changed canonical source token IDs for {uid}")
            if str(item.get("source_reference") or "") != expected.source_reference:
                raise SemanticMappingValidationError(f"Model changed canonical source reference for {uid}")
            rel = [str(x) for x in item.get("relationships") or []]
            if not rel or any(x not in RELATIONSHIPS for x in rel):
                raise SemanticMappingValidationError(f"Invalid semantic relationship for {uid}")
            status = str(item.get("meaning_status") or "")
            if status not in MEANING_STATUSES:
                raise SemanticMappingValidationError(f"Invalid meaning status for {uid}")
            try:
                confidence = float(item.get("confidence"))
            except Exception as exc:
                raise SemanticMappingValidationError(f"Invalid confidence for {uid}") from exc
            if not 0 <= confidence <= 1:
                raise SemanticMappingValidationError(f"Confidence out of range for {uid}")

            clean_spans: list[dict[str, Any]] = []
            spans = item.get("target_spans") or []
            if not isinstance(spans, list):
                raise SemanticMappingValidationError(f"target_spans must be an array for {uid}")
            for span in spans:
                if not isinstance(span, dict):
                    raise SemanticMappingValidationError(f"Invalid target span for {uid}")
                ref = str(span.get("reference") or "")
                quote = str(span.get("quote") or "")
                if ref not in segment_by_ref:
                    raise SemanticMappingValidationError(f"Model referenced target verse outside searched passage: {ref}")
                if not quote:
                    raise SemanticMappingValidationError(f"Overt target span has empty quote for {uid}")
                seg_text = segment_by_ref[ref].text
                start = span.get("start"); end = span.get("end")
                # The model is never told what indexing convention start/end use, and
                # LLMs are unreliable at counting exact character offsets in complex/
                # non-Latin scripts (Devanagari conjuncts/matras and similar). Treat
                # any offsets it supplies as an unverified hint, not a source of
                # truth: the real anti-hallucination guard is that the literal quote
                # text must occur exactly once, unambiguously, in the target segment.
                # Trust given offsets only when they already agree with that; never
                # reject solely because the model's own offset arithmetic was wrong.
                offsets_confirmed = (
                    isinstance(start, int) and isinstance(end, int)
                    and 0 <= start <= end <= len(seg_text) and seg_text[start:end] == quote
                )
                if not offsets_confirmed:
                    positions = _literal_positions(seg_text, quote)
                    if len(positions) != 1:
                        raise SemanticMappingValidationError(f"Target quote for {uid} in {ref} was not found as an unambiguous exact match in the target segment; hallucinated or ambiguous text rejected")
                    start, end = positions[0]
                clean_spans.append({"reference": ref, "quote": quote, "start": start, "end": end})

            if status == "PRESERVED" and not clean_spans and not ({"IMPLICIT", "GRAMMATICALLY_ENCODED"} & set(rel)):
                raise SemanticMappingValidationError(f"PRESERVED mapping without overt span must be explicitly implicit/grammatical for {uid}")
            if clean_spans and status == "NOT_LOCATED":
                raise SemanticMappingValidationError(f"NOT_LOCATED mapping cannot contain target spans for {uid}")

            target_refs = {s["reference"] for s in clean_spans}
            if len(target_refs) > 1 and "SPLIT_ACROSS_VERSES" not in rel:
                rel.append("SPLIT_ACROSS_VERSES")
            if clean_spans and all(r != expected.source_reference for r in target_refs):
                if not any(x in rel for x in ("CROSS_VERSE_MOVED", "CROSS_VERSE_REORDERED", "VERSIFICATION_DIFFERENCE")):
                    rel.append("CROSS_VERSE_MOVED")

            clean = dict(item)
            clean["source_unit_id"] = uid
            clean["source_token_ids"] = token_ids
            clean["source_reference"] = expected.source_reference
            clean["target_spans"] = clean_spans
            clean["relationships"] = list(dict.fromkeys(rel))
            clean["meaning_status"] = status
            clean["confidence"] = confidence
            clean_mappings.append(clean)

        clean_unresolved: list[dict[str, Any]] = []
        for item in unresolved:
            if not isinstance(item, dict):
                raise SemanticMappingValidationError("Unresolved row must be an object")
            uid = str(item.get("source_unit_id") or "")
            reason = str(item.get("reason") or "")
            if uid not in unit_by_id:
                raise SemanticMappingValidationError(f"Unknown unresolved source unit: {uid}")
            if uid in seen:
                raise SemanticMappingValidationError(f"Source unit cannot be both mapped and unresolved: {uid}")
            if reason not in {"NOT_LOCATED", "AMBIGUOUS", "MODEL_UNCERTAIN", "SEARCH_BUDGET_EXHAUSTED"}:
                raise SemanticMappingValidationError(f"Invalid unresolved reason for {uid}")
            if reason == "SEARCH_BUDGET_EXHAUSTED" and not allow_search_exhausted:
                raise SemanticMappingValidationError("SEARCH_BUDGET_EXHAUSTED is a Bridge engine state, not a model-returnable conclusion")
            if any(x["source_unit_id"] == uid for x in clean_unresolved):
                raise SemanticMappingValidationError(f"Duplicate unresolved source unit: {uid}")
            clean_unresolved.append({"source_unit_id": uid, "reason": reason, "detail": str(item.get("detail") or "")})

        returned = seen | {x["source_unit_id"] for x in clean_unresolved}
        missing = set(unit_by_id) - returned
        # Model omission is treated as unresolved, never as a semantic omission.
        for uid in sorted(missing):
            clean_unresolved.append({"source_unit_id": uid, "reason": "MODEL_UNCERTAIN", "detail": "Model response omitted this requested source unit."})
        return {"mappings": clean_mappings, "unresolved_source_units": clean_unresolved, "passage_assessment": assessment if not missing else "NEEDS_REVIEW"}


def _literal_positions(text: str, quote: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start = 0
    while True:
        i = text.find(quote, start)
        if i < 0:
            return out
        out.append((i, i + len(quote)))
        start = i + max(1, len(quote))


def mapping_state_for_review(mapping: dict[str, Any], origin_reference: str) -> dict[str, Any]:
    """Translate semantic mapping to a UI/backend-safe review state.

    This never returns the ambiguous legacy state "Nothing to Select".
    """
    spans = list(mapping.get("target_spans") or [])
    rel = set(mapping.get("relationships") or [])
    status = str(mapping.get("meaning_status") or "UNCERTAIN")
    if spans:
        refs = {str(s.get("reference") or "") for s in spans}
        if refs == {origin_reference}:
            label = "found_this_verse"
        elif len(refs) > 1:
            label = "split_across_verses"
        else:
            label = "found_another_verse"
        return {"state": label, "selectable": True, "targetSpans": spans, "meaningStatus": status, "relationships": sorted(rel)}
    if "IMPLICIT" in rel or "GRAMMATICALLY_ENCODED" in rel:
        return {"state": "represented_implicitly", "selectable": False, "targetSpans": [], "meaningStatus": status, "relationships": sorted(rel)}
    if status in {"NOT_LOCATED", "POSSIBLE_PROBLEM"}:
        return {"state": "target_not_located", "selectable": False, "targetSpans": [], "meaningStatus": status, "relationships": sorted(rel)}
    return {"state": "needs_passage_review", "selectable": False, "targetSpans": [], "meaningStatus": status, "relationships": sorted(rel)}
