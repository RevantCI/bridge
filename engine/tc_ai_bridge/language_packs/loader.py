"""Load, validate and compile a Language QA rule pack.

The schema is documented in docs/LANGUAGE_QA_RULE_PACK.md. The match
primitives form a small, closed set. This is deliberately not a grammar
engine:

- token-context rules look at one pair of adjacent words separated only by
  whitespace. The previous word is split into its base and an optional
  linking consonant: `அந்தக்` is base `அந்த` plus link `க`. `prev` conditions
  test the base; `next` conditions test the following word. `link` says
  which shape the rule is about:
  - "none": bare, the linking consonant is missing;
  - "mismatch": linked with the wrong consonant;
  - "any": bare or correctly linked.
- regex rules match one pattern over the verse's visible text, or over its
  raw text for markup-level integrity rules. The finding span is the named
  group `span`, or the whole match.
- conditions are:
  - lexical / notLexical: exact NFC token sets;
  - suffix: a regex searched at the token's end;
  - regex: searched anywhere in the token;
  - minLength;
  - initial: the first character is in a set;
  - prefix: the token starts with one of these stems;
  - listRef: membership of a named list, e.g. a house-style list.

A project may narrow a bundled rule, never widen it. An override can
disable a rule, take it off inline display, or add abstains. Anything else
is refused and reported (docs/DECISIONS.md).
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import regex

PACKS_DIR = Path(__file__).resolve().parent
HARD = frozenset("கசதப")
PULLI = "்"
CATEGORY_LAYERS = {
    "sandhi": "pattern", "word-joining": "pattern", "typo": "pattern",
    "punctuation": "integrity", "spacing": "integrity", "unicode": "integrity",
    "termbase": "housestyle", "name": "housestyle",
}
SEVERITIES = ("high", "medium", "low")
CONFIDENCES = ("high", "medium", "low")
LINKS = ("none", "mismatch", "any")
FIXES = ("insert-link", "replace-link", "fuse-link", "replace", "expand")
CONDITION_KEYS = {"lexical", "notLexical", "suffix", "regex", "minLength", "initial", "prefix", "listRef"}
RULE_KEYS = {"id", "version", "legacyId", "enabled", "category", "layer", "severity", "confidence",
             "inline", "inlineSignOff", "title", "message", "rationale", "match", "abstain", "fix",
             "examples", "provenance"}
OVERRIDE_RULE_KEYS = {"enabled", "inline", "abstain"}
OVERRIDES_PATH = Path(".apps") / "translationCoreAI" / "language-packs"


class PackError(ValueError):
    """A pack that must not be used: bad schema, or a failing example."""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


@dataclass(frozen=True)
class Condition:
    lexical: frozenset | None = None
    not_lexical: frozenset = frozenset()
    suffix: Any = None
    pattern: Any = None
    min_length: int = 0
    initial: frozenset | None = None
    prefix: tuple = ()
    list_ref: str | None = None

    def matches(self, token: str, lists: dict[str, frozenset]) -> bool:
        if self.lexical is not None and token not in self.lexical:
            return False
        if token in self.not_lexical:
            return False
        if len(token) < self.min_length:
            return False
        if self.initial is not None and token[:1] not in self.initial:
            return False
        if self.prefix and not token.startswith(self.prefix):
            return False
        if self.suffix is not None and not self.suffix.search(token):
            return False
        if self.pattern is not None and not self.pattern.search(token):
            return False
        if self.list_ref is not None and token not in lists.get(self.list_ref, frozenset()):
            return False
        return True


def _condition(raw: Any, where: str) -> Condition:
    if not isinstance(raw, dict) or not raw:
        raise PackError(f"{where}: a condition must be a non-empty object")
    unknown = set(raw) - CONDITION_KEYS
    if unknown:
        raise PackError(f"{where}: unknown condition keys {sorted(unknown)}")

    def words(key: str) -> frozenset | None:
        if key not in raw:
            return None
        value = raw[key]
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise PackError(f"{where}.{key}: must be a list of non-empty strings")
        return frozenset(nfc(v) for v in value)

    def compiled(key: str, anchor_end: bool) -> Any:
        if key not in raw:
            return None
        if not isinstance(raw[key], str) or not raw[key]:
            raise PackError(f"{where}.{key}: must be a non-empty regex string")
        source = raw[key] if not anchor_end or raw[key].endswith("$") else raw[key] + "$"
        try:
            return regex.compile(nfc(source))
        except regex.error as exc:
            raise PackError(f"{where}.{key}: bad regex: {exc}") from exc

    min_length = raw.get("minLength", 0)
    if not isinstance(min_length, int) or min_length < 0:
        raise PackError(f"{where}.minLength: must be a non-negative integer")
    list_ref = raw.get("listRef")
    if list_ref is not None and (not isinstance(list_ref, str) or not list_ref):
        raise PackError(f"{where}.listRef: must be a list name")
    return Condition(
        lexical=words("lexical"), not_lexical=words("notLexical") or frozenset(),
        suffix=compiled("suffix", True), pattern=compiled("regex", False), min_length=min_length,
        initial=words("initial"), prefix=tuple(sorted(words("prefix") or ())), list_ref=list_ref,
    )


@dataclass(frozen=True)
class Abstain:
    prev: Condition | None
    next: Condition | None
    origin: str


@dataclass
class Rule:
    id: str
    version: int
    legacy_id: str | None
    enabled: bool
    category: str
    layer: str
    severity: str
    confidence: str
    inline: bool
    message: str
    rationale: str
    match_type: str
    prev: Condition | None = None
    next: Condition | None = None
    link: str = "none"
    pattern: Any = None
    on: str = "visible"
    abstain: list[Abstain] = field(default_factory=list)
    fix: dict[str, Any] | None = None
    examples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    # The maintainer's sign-off for drawing this rule inline below the
    # benchmark's precision floor: {by, date, reason, precisionStrict}.
    sign_off: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        """The `rule` field of its findings, and the name finding ids are
        derived from. A migrated rule keeps the name it had before migration
        (`legacyId`), so its findings keep their ids and their decisions."""
        return self.legacy_id or self.id


def _split(token: str) -> tuple[str, str | None]:
    """(base, linking consonant) of a previous word."""
    if len(token) > 2 and token[-1] == PULLI and token[-2] in HARD:
        return token[:-2], token[-2]
    return token, None


@dataclass(frozen=True)
class Candidate:
    rule: Rule
    start: int          # visible offsets, or raw offsets when raw is True
    end: int
    replacement: str | None
    message: str
    rationale: str
    raw: bool = False


class RulePack:
    def __init__(self, name: str, version: str, language: str, rules: list[Rule],
                 description: str = "", problems: list[str] | None = None) -> None:
        self.name = name
        self.version = version
        self.language = language
        self.description = description
        self.rules = rules
        self.problems = list(problems or [])
        self.pair_rules = [r for r in rules if r.enabled and r.match_type == "token-context"]
        self.regex_rules = [r for r in rules if r.enabled and r.match_type == "regex"]
        initials: set[str] = set()
        for rule in self.pair_rules:
            if rule.next is None or (rule.next.initial is None and rule.next.lexical is None):
                initials = set()
                break
            initials |= set(rule.next.initial or ())
            initials |= {w[:1] for w in (rule.next.lexical or ())}
        self._next_initials = frozenset(initials) if initials else None

    @property
    def pack_version(self) -> str:
        return f"{self.name}@{self.version}"

    def by_id(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    def fingerprint(self) -> str:
        """Changes whenever anything that affects findings changes, including
        a project's overrides; folded into the scan's per-chapter cache key."""
        state = [(r.id, r.version, r.enabled, r.inline, len(r.abstain)) for r in self.rules]
        return hashlib.sha1(json.dumps([self.pack_version, state]).encode()).hexdigest()

    # -- evaluation ---------------------------------------------------------

    def pair_candidates(self, text: str, prev_match: Any, next_match: Any,
                        lists: dict[str, frozenset]) -> list[Candidate]:
        """Findings for one pair of adjacent words separated by whitespace only."""
        next_word = nfc(next_match.group())
        if self._next_initials is not None and next_word[:1] not in self._next_initials:
            return []
        prev_word = nfc(prev_match.group())
        base, link = _split(prev_word)
        out: list[Candidate] = []
        for rule in self.pair_rules:
            if rule.link == "none" and link is not None:
                continue
            if rule.link == "mismatch" and (link is None or link == next_word[:1]):
                continue
            if rule.link == "any" and link is not None and link != next_word[:1]:
                continue
            if rule.prev is not None and not rule.prev.matches(base, lists):
                continue
            if rule.next is not None and not rule.next.matches(next_word, lists):
                continue
            if any((a.prev is None or a.prev.matches(base, lists))
                   and (a.next is None or a.next.matches(next_word, lists)) for a in rule.abstain):
                continue
            initial = next_word[:1]
            raw_prev = text[prev_match.start():prev_match.end()]
            raw_gap = text[prev_match.end():next_match.start()]
            raw_next = text[next_match.start():next_match.end()]
            kind = (rule.fix or {}).get("type")
            if kind == "insert-link":
                replacement = raw_prev + initial + PULLI + raw_gap + raw_next
            elif kind == "replace-link":
                replacement = raw_prev[:-2] + initial + PULLI + raw_gap + raw_next
            elif kind == "fuse-link":
                stem = raw_prev[:-2] if link is not None else raw_prev
                replacement = stem + initial + PULLI + raw_next
            else:
                replacement = None
            values = {"prev": base, "word": prev_word, "next": next_word, "initial": initial,
                      "link": link or "", "fix": replacement or ""}
            out.append(Candidate(rule, prev_match.start(), next_match.end(), replacement,
                                 rule.message.format(**values), rule.rationale.format(**values)))
        return out

    def regex_candidates(self, visible: str, raw: str) -> list[Candidate]:
        out: list[Candidate] = []
        for rule in self.regex_rules:
            subject = raw if rule.on == "raw" else visible
            for match in rule.pattern.finditer(subject):
                group = "span" if "span" in rule.pattern.groupindex else 0
                start, end = match.span(group)
                if start == end:
                    continue
                kind = (rule.fix or {}).get("type")
                if kind == "replace":
                    replacement = rule.fix["text"]
                elif kind == "expand":
                    replacement = match.expand(rule.fix["template"])
                else:
                    replacement = None
                values = {"span": subject[start:end], "fix": replacement or ""}
                out.append(Candidate(rule, start, end, replacement, rule.message.format(**values),
                                     rule.rationale.format(**values), raw=rule.on == "raw"))
        return out


def _rule(raw: dict[str, Any], where: str) -> Rule:
    if not isinstance(raw, dict):
        raise PackError(f"{where}: a rule must be an object")
    unknown = set(raw) - RULE_KEYS
    if unknown:
        raise PackError(f"{where}: unknown rule keys {sorted(unknown)}")
    for key in ("id", "version", "category", "severity", "confidence", "message", "match"):
        if key not in raw:
            raise PackError(f"{where}: missing '{key}'")
    rule_id = raw["id"]
    where = f"rule {rule_id}"
    if not isinstance(rule_id, str) or not regex.fullmatch(r"[a-z][a-z0-9.-]*", rule_id):
        raise PackError(f"{where}: id must be lowercase dotted, e.g. sandhi.vallinam.demonstrative")
    if not isinstance(raw["version"], int) or raw["version"] < 1:
        raise PackError(f"{where}: version must be a positive integer")
    if raw["category"] not in CATEGORY_LAYERS:
        raise PackError(f"{where}: unknown category {raw['category']!r}")
    if raw["severity"] not in SEVERITIES or raw["confidence"] not in CONFIDENCES:
        raise PackError(f"{where}: severity and confidence must be high, medium or low")
    message = raw["message"].get("en") if isinstance(raw["message"], dict) else None
    if not isinstance(message, str) or not message:
        raise PackError(f"{where}: message.en is required")
    match = raw["match"]
    if not isinstance(match, dict) or match.get("type") not in {"token-context", "regex"}:
        raise PackError(f"{where}: match.type must be token-context or regex")
    rule = Rule(
        id=rule_id, version=raw["version"], legacy_id=raw.get("legacyId"),
        enabled=bool(raw.get("enabled", True)), category=raw["category"],
        layer=raw.get("layer", CATEGORY_LAYERS[raw["category"]]),
        severity=raw["severity"], confidence=raw["confidence"], inline=bool(raw.get("inline", False)),
        message=message, rationale=str(raw.get("rationale", "")), match_type=match["type"],
        fix=raw.get("fix"), examples=raw.get("examples") or {}, source=raw,
        sign_off=raw.get("inlineSignOff"),
    )
    if rule.sign_off is not None and (not isinstance(rule.sign_off, dict)
                                      or not rule.sign_off.get("by") or not rule.sign_off.get("date")):
        raise PackError(f"{where}: inlineSignOff needs at least 'by' and 'date'")
    if match["type"] == "token-context":
        if match.get("gap", "whitespace") != "whitespace":
            raise PackError(f"{where}: gap must be 'whitespace' (punctuation, digits and markup abstain)")
        rule.prev = _condition(match["prev"], f"{where}.match.prev") if "prev" in match else None
        rule.next = _condition(match["next"], f"{where}.match.next") if "next" in match else None
        rule.link = match.get("link", "none")
        if rule.link not in LINKS:
            raise PackError(f"{where}: match.link must be one of {LINKS}")
    else:
        if match.get("on", "visible") not in {"visible", "raw"}:
            raise PackError(f"{where}: match.on must be visible or raw")
        if match.get("on") == "raw" and rule.layer != "integrity":
            raise PackError(f"{where}: only integrity rules may match raw text (markup)")
        try:
            rule.pattern = regex.compile(nfc(match["pattern"]))
        except (KeyError, regex.error) as exc:
            raise PackError(f"{where}: match.pattern: {exc}") from exc
        rule.on = match.get("on", "visible")
    rule.abstain = [_abstain(entry, f"{where}.abstain[{i}]") for i, entry in enumerate(raw.get("abstain") or [])]
    if rule.fix is not None:
        if not isinstance(rule.fix, dict) or rule.fix.get("type") not in FIXES:
            raise PackError(f"{where}: fix.type must be one of {FIXES}")
        if rule.fix["type"] in {"insert-link", "replace-link", "fuse-link"} and rule.match_type != "token-context":
            raise PackError(f"{where}: {rule.fix['type']} applies to token-context rules only")
        if rule.fix["type"] == "replace" and not isinstance(rule.fix.get("text"), str):
            raise PackError(f"{where}: fix.text is required for replace")
        if rule.fix["type"] == "expand" and not isinstance(rule.fix.get("template"), str):
            raise PackError(f"{where}: fix.template is required for expand")
    return rule


def _abstain(raw: Any, where: str) -> Abstain:
    if not isinstance(raw, dict) or not ({"prev", "next"} & set(raw)):
        raise PackError(f"{where}: an abstain needs a prev and/or next condition")
    unknown = set(raw) - {"prev", "next", "origin"}
    if unknown:
        raise PackError(f"{where}: unknown abstain keys {sorted(unknown)}")
    return Abstain(
        prev=_condition(raw["prev"], f"{where}.prev") if "prev" in raw else None,
        next=_condition(raw["next"], f"{where}.next") if "next" in raw else None,
        origin=str(raw.get("origin", "")),
    )


def _read_pack(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        meta = json.loads((directory / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackError(f"{directory.name}: cannot read pack.json: {exc}") from exc
    for key in ("pack", "version", "language", "rules"):
        if key not in meta:
            raise PackError(f"{directory.name}: pack.json is missing '{key}'")
    raws = []
    for entry in meta["rules"]:
        try:
            raws.append(json.loads((directory / entry).read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise PackError(f"{directory.name}: cannot read {entry}: {exc}") from exc
    return meta, raws


def _build(meta: dict[str, Any], raws: list[dict[str, Any]], problems: list[str] | None = None) -> RulePack:
    rules = [_rule(raw, f"{meta['pack']}:{i}") for i, raw in enumerate(raws)]
    ids = [r.id for r in rules]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise PackError(f"{meta['pack']}: duplicate rule ids {sorted(duplicates)}")
    return RulePack(meta["pack"], str(meta["version"]), meta["language"], rules,
                    str(meta.get("description", "")), problems)


def run_examples(pack: RulePack) -> None:
    """Every rule's examples, through the real scan path. An incorrect example
    must yield a finding of that rule on exactly its span, with its fix; a
    correct one must yield none of that rule. The first failure raises."""
    from ..language_qa import scan_text  # the one scan path; imported late (it imports this module lazily)

    for rule in pack.rules:
        if not rule.enabled:
            continue
        rule_id = f"{pack.name}/{rule.id}"
        for index, example in enumerate(rule.examples.get("incorrect", [])):
            findings = [f for f in scan_text(example["text"], book="x", chapter="1", verse="1", tamil=True,
                                             pack=pack, lists=_example_lists(example))["findings"]
                        if f["ruleId"] == rule_id]
            span = nfc(example["span"])
            hit = next((f for f in findings if nfc(f["originalText"]) == span), None)
            where = f"rule {rule.id}: incorrect example {index + 1} ({example.get('origin', 'no origin')})"
            if hit is None:
                raise PackError(f"{where}: expected a finding on {span!r}, got "
                                f"{[f['originalText'] for f in findings]!r}")
            if "fix" in example and example["fix"] is not None and nfc(hit["suggestedReplacement"] or "") != nfc(example["fix"]):
                raise PackError(f"{where}: expected fix {example['fix']!r}, got {hit['suggestedReplacement']!r}")
        for index, example in enumerate(rule.examples.get("correct", [])):
            findings = [f for f in scan_text(example["text"], book="x", chapter="1", verse="1", tamil=True,
                                             pack=pack, lists=_example_lists(example))["findings"]
                        if f["ruleId"] == rule_id]
            if findings:
                raise PackError(f"rule {rule.id}: correct example {index + 1} ({example.get('origin', 'no origin')}) "
                                f"was flagged: {[f['originalText'] for f in findings]!r}")


def _example_lists(example: dict[str, Any]) -> dict[str, frozenset]:
    return {name: frozenset(nfc(w) for w in words) for name, words in (example.get("lists") or {}).items()}


def apply_overrides(pack: RulePack, overrides: dict[str, Any] | None) -> RulePack:
    """A copy of `pack` narrowed by a project's overrides. Only narrowing is
    accepted: enabled=false, inline=false, extra abstains. Anything else is
    refused, the rest of the override still applies, and each refusal is
    listed in `problems` for the panel's coverage notes."""
    if not overrides:
        return pack
    problems: list[str] = []
    rules = [copy.copy(rule) for rule in pack.rules]
    for rule in rules:
        rule.abstain = list(rule.abstain)
    by_id = {rule.id: rule for rule in rules}
    entries = overrides.get("rules") if isinstance(overrides, dict) else None
    if not isinstance(entries, dict):
        return RulePack(pack.name, pack.version, pack.language, rules, pack.description,
                        ["override ignored: expected {\"rules\": {<rule id>: {...}}}"])
    for rule_id, change in entries.items():
        rule = by_id.get(rule_id)
        if rule is None:
            problems.append(f"override for unknown rule {rule_id!r} ignored")
            continue
        if not isinstance(change, dict):
            problems.append(f"override for {rule_id} ignored: not an object")
            continue
        for key in sorted(set(change) - OVERRIDE_RULE_KEYS):
            problems.append(f"override {rule_id}.{key} refused: an override may only disable, "
                            "take off inline, or add abstains")
        if "enabled" in change:
            if change["enabled"] is False:
                rule.enabled = False
            elif change["enabled"] is not True or not rule.enabled:
                problems.append(f"override {rule_id}.enabled refused: an override cannot enable a rule")
        if "inline" in change:
            if change["inline"] is False:
                rule.inline = False
            elif change["inline"] is not True or not rule.inline:
                problems.append(f"override {rule_id}.inline refused: an override cannot draw a rule inline")
        for index, entry in enumerate(change.get("abstain") or []):
            try:
                rule.abstain.append(_abstain(entry, f"override {rule_id}.abstain[{index}]"))
            except PackError as exc:
                problems.append(f"{exc}; ignored")
    return RulePack(pack.name, pack.version, pack.language, rules, pack.description, problems)


def load_pack(name: str = "ta-irv", *, directory: Path | None = None) -> RulePack:
    """Load, compile and self-test a bundled pack (or one in `directory`)."""
    meta, raws = _read_pack(directory or PACKS_DIR / name)
    pack = _build(meta, raws)
    run_examples(pack)
    return pack


_LOADED: dict[str, RulePack] = {}
_LOAD_LOCK = threading.Lock()


def default_pack(name: str = "ta-irv") -> RulePack:
    """The bundled pack, loaded once per process, lazily on first use.

    Serialised: without the lock, a status poll arriving during the worker's
    first load ran a second full load (examples included, ~160 ms) and the
    poll's p95 went from 0.3 ms to 80 ms (layered-rules Phase 3 latency gate)."""
    pack = _LOADED.get(name)
    if pack is None:
        with _LOAD_LOCK:
            pack = _LOADED.get(name)
            if pack is None:
                pack = _LOADED[name] = load_pack(name)
    return pack


def loaded_pack(name: str = "ta-irv") -> RulePack | None:
    """The bundled pack if it is already loaded; never loads it. For request
    paths that must not wait on a first load."""
    return _LOADED.get(name)


default_pack.cache_clear = _LOADED.clear  # type: ignore[attr-defined]  # as with lru_cache; the pack builder uses it


def load_project_overrides(project_path: Path | str, name: str = "ta-irv") -> tuple[dict[str, Any] | None, list[str]]:
    path = Path(project_path) / OVERRIDES_PATH / name / "overrides.json"
    if not path.exists():
        return None, []
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (OSError, ValueError) as exc:
        return None, [f"project overrides for {name} ignored: {exc}"]


def examples_of(pack: RulePack) -> Iterable[tuple[Rule, str, dict[str, Any]]]:
    for rule in pack.rules:
        for kind in ("incorrect", "correct"):
            for example in rule.examples.get(kind, []):
                yield rule, kind, example
