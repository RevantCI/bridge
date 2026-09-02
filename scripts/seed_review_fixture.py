"""Seed a Philippians 1:3-6 review fixture project for Stage 9A.

Bridge ships with no embedding provider (``SemanticEmbeddingProvider`` has
``available = False``), so the Stage 6B passage-reordering behaviour that the
review UI is most interesting against cannot be produced by the running app
on its own. This script builds a real translationCore-compatible project,
runs the Stage 5-8 pipeline against it with a fixture embedding provider, and
leaves the results persisted in the project's own companion database.

That is enough for the review UI, because the review surface only ever reads
persisted findings - it never re-runs analysis. Open the printed path in
Bridge and Alignment Review's QA mode will show the seeded queue.

    python scripts/seed_review_fixture.py [destination]

The generated project is disposable: delete the directory to remove it. It is
deliberately generated rather than committed, matching the repository's
existing practice of not committing companion databases.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unicodedata

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

from tc_ai_bridge.meaning_analysis import MeaningAnalysisEngine  # noqa: E402
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime  # noqa: E402
from tc_ai_bridge.project_registry import ProjectRegistry  # noqa: E402
from tc_ai_bridge.qa_audit import QaAuditEngine  # noqa: E402
from tc_ai_bridge.semantic_location import (  # noqa: E402
    SemanticEmbeddingProvider,
    SemanticLocationEngine,
)
from tc_ai_bridge.tc_project import TranslationCoreProject  # noqa: E402


# IRV Tamil Philippians 1:3-6. The Greek and Tamil verse orders differ: Greek
# 1:3 is realized in Tamil 1:6, 1:4 in 1:4, 1:5 in 1:3 and 1:6 in 1:5. That
# reordering is the point of the fixture - a reviewer must be able to see it
# without any of it being reported as an omission.
TAMIL_PHP_1 = {
    "3": "நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல் இதுவரைக்கும் நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்,",
    "4": "நான் பண்ணுகிற ஒவ்வொரு விண்ணப்பத்திலும் உங்கள் அனைவருக்காகவும் எப்பொழுதும் மகிழ்ச்சியோடு ஜெபம் செய்து,",
    "5": "உங்களில் நல்ல செயலைத் தொடங்கினவர் அதை இயேசு கிறிஸ்துவின் நாள் வரை நடத்தி வருவார் என்று நம்பி,",
    "6": "நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்.",
}

PHP_PAIRS = [
    ("εὐχαριστέω", "ஸ்தோத்திரிக்கிறேன்"), ("θεός", "தேவனை"), ("μνεία", "நினைக்கும்"),
    ("πάντοτε", "எப்பொழுதும்"), ("δέησις", "விண்ணப்பத்திலும்"), ("χαρά", "மகிழ்ச்சியோடு"),
    ("ποιέω", "செய்து"), ("κοινωνία", "ஐக்கியப்பட்டிருப்பதால்"), ("εὐαγγέλιον", "நற்செய்தி"),
    ("πρῶτος", "முதல்"), ("ἡμέρα", "நாள்"), ("νῦν", "இதுவரைக்கும்"), ("πείθω", "நம்பி"),
    ("ἐνάρχομαι", "தொடங்கினவர்"), ("ἔργον", "செயலைத்"), ("ἀγαθός", "நல்ல"),
    ("ἐπιτελέω", "நடத்தி வருவார்"), ("χριστός", "கிறிஸ்துவின்"), ("Ἰησοῦς", "இயேசு"),
]


def _norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


class FixtureEmbeddingProvider(SemanticEmbeddingProvider):
    """Offline, deterministic stand-in for a real multilingual retriever.

    Candidate retrieval only, never a meaning judge - the same contract the
    real provider interface declares.
    """

    provider_id = "stage9a-review-fixture"
    provider_version = "v1"
    model_id = "stage9a-review-fixture"
    normalization = "L2"
    languages = ("el", "hbo", "arc", "ta", "en")
    offline = True
    available = True

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = {_norm(key): value for key, value in vectors.items()}
        self.dimensions = len(next(iter(vectors.values())))
        self.model_hash = hashlib.sha256(
            json.dumps(self.vectors, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors.get(_norm(text), [0.0] * self.dimensions) for text in texts]


def paired_vectors(pairs: list[tuple[str, str]]) -> dict[str, list[float]]:
    vectors: dict[str, list[float]] = {}
    for index, (source, target) in enumerate(pairs):
        vector = [0.0] * len(pairs)
        vector[index] = 1.0
        vectors[source] = vector
        vectors[target] = vector
    return vectors


def build_project(root: Path) -> Path:
    """Write a translationCore-compatible single-book project to disk."""
    if root.exists():
        raise SystemExit(
            f"{root} already exists. Delete it first, or pass a different destination."
        )
    (root / "php").mkdir(parents=True)
    alignment = root / ".apps" / "translationCore" / "alignmentData" / "php"
    alignment.mkdir(parents=True)

    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "Philippians"},
        "target_language": {"id": "ta", "name": "Tamil", "direction": "ltr"},
        "resource": {"id": "irv"},
        "tc_version": "8",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (root / "php" / "1.json").write_text(
        json.dumps(TAMIL_PHP_1, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (alignment / "1.json").write_text(json.dumps(
        {reference: {"alignments": [], "wordBank": []} for reference in TAMIL_PHP_1},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["\\id PHP", "\\c 1", "\\p"]
    lines.extend(f"\\v {verse} {text}" for verse, text in TAMIL_PHP_1.items())
    (root / "php.usfm").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def project_identity(root: Path) -> str:
    """Mint the identity Bridge itself will use when it opens this project.

    The companion database is bound to a project id, and Bridge refuses to
    open one bound to a different identity. That id comes from the project
    registry, which persists it in the project's own ``.bridge/project.json``
    - so registering here through a throwaway registry file writes the
    identity into the project, and the app reuses the same id later rather
    than minting a new one and rejecting the seeded database.
    """
    scratch = root.parent / f"{root.name}-seed-registry.json"
    registry = ProjectRegistry(scratch, root.parent / "managed")
    registered = registry.register(root, touch=True)
    scratch.unlink(missing_ok=True)
    return str(registered["projectId"])


def seed(root: Path) -> dict[str, object]:
    """Run Stages 5-8 over the fixture and persist the results."""
    runtime = PassageSemanticRuntime(TranslationCoreProject(root), project_identity(root))
    provider = FixtureEmbeddingProvider(paired_vectors(PHP_PAIRS))

    location = SemanticLocationEngine(runtime, provider).run_range("1", "3", "1", "6")
    meaning = MeaningAnalysisEngine(runtime).run_range(
        "1", "3", "1", "6", location_run_id=location["id"])
    audit = QaAuditEngine(runtime).run_range(
        "1", "3", "1", "6", meaning_run_id=meaning["id"])

    queue = runtime.qa_review.get_queue(limit=200)
    return {
        "locationRun": location["id"],
        "relationships": len(location["relationships"]),
        "reordered": location["diagnostics"].get("reordered"),
        "crossVerse": location["diagnostics"].get("crossVerse"),
        "meaningRun": meaning["id"],
        "qaRun": audit["id"],
        "findings": len(audit["findings"]),
        "queueTotal": queue["totalCount"],
        "companionDatabase": str(runtime.path),
        "projectId": runtime.project_id,
    }


def main() -> int:
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "php-review-fixture"
    root = build_project(destination.resolve())
    summary = seed(root)

    print(f"Seeded review fixture at: {root}")
    print()
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print()
    if not summary["relationships"]:
        print("WARNING: no relationships were produced; the review queue will be sparse.")
    print("Open that folder in Bridge, then choose Alignment Review from the editor toolbar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
