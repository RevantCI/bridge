"""Generate a ranked, unconfirmed IRVTam Stage 3 validation set."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from tc_ai_bridge.ai_client import OpenAIResponsesClient
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.semantic_corpus_discovery import (
    candidates_from_run, propose_corpus_batches, rank_representative_candidates,
    structural_screen_candidates, validation_payload, write_validation_payload,
)
from tc_ai_bridge.semantic_mapping import (
    PassageSearchBudget, SemanticMappingEngine, SemanticMappingStore,
    SemanticSourceRepository,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "docs" / "validation" / "irvtam-semantic-mapping-candidates.json"))
    parser.add_argument("--max-batches", type=int, default=10)
    parser.add_argument("--units-per-batch", type=int, default=10)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--structural-only", action="store_true",
        help="Do not transmit corpus text; generate deterministic local screening candidates only.",
    )
    args = parser.parse_args()

    resource_root = ENGINE / "resources" / "semantic_mapping"
    source_db = resource_root / "bridge_semantic_source_v0.3.sqlite"
    corpora = [
        (resource_root / "regression" / "43LUKIRVTam.SFM", "LUK"),
        (resource_root / "regression" / "51PHPIRVTam.SFM", "PHP"),
    ]
    repository = SemanticSourceRepository(source_db)
    budget = PassageSearchBudget(
        max_model_calls=3, max_adjacent_layers=2, max_windows=5,
        max_segments=48, max_target_characters=30_000,
    )
    settings = AppSettings()
    if args.structural_only:
        candidates = structural_screen_candidates(repository, corpora, limit=args.limit)
        model = "LOCAL_DETERMINISTIC_STRUCTURAL_SCREEN"
    else:
        api_key = settings.get_api_key()
        if not api_key:
            raise SystemExit("No Bridge/OpenAI API key is configured.")
        client = OpenAIResponsesClient(
            api_key, model=settings.model, base_url=settings.api_base_url,
            reasoning_effort="medium", timeout=240.0,
        )
        batches = propose_corpus_batches(
            repository, corpora, max_batches=args.max_batches, units_per_batch=args.units_per_batch,
        )
        proposed: list[dict] = []
        diagnostics: list[dict] = []
        cache = SemanticMappingStore(ENGINE / "build" / "semantic-corpus-discovery")
        for number, (_, index, window, units) in enumerate(batches, 1):
            print(f"[{number}/{len(batches)}] {index.book} {window.id}: {len(units)} source units", flush=True)
            try:
                run = SemanticMappingEngine(repository, client, search_budget=budget).map_units(
                    target_index=index, source_units=units, store=cache, force=args.force,
                )
                proposed.extend(candidates_from_run(run))
                diagnostics.append({
                    "book": index.book, "windowId": window.id, "status": "complete",
                    "cacheHit": run.cache_hit, "mapped": len(run.result.get("mappings", [])),
                    "unresolved": len(run.result.get("unresolved_source_units", [])),
                    "searchedWindows": list(run.searched_windows),
                })
                print(
                    f"  mapped={len(run.result.get('mappings', []))} "
                    f"unresolved={len(run.result.get('unresolved_source_units', []))} "
                    f"windows={len(run.searched_windows)} cache={run.cache_hit}",
                    flush=True,
                )
            except Exception as exc:
                diagnostics.append({
                    "book": index.book, "windowId": window.id, "status": "rejected",
                    "errorType": type(exc).__name__, "detail": str(exc),
                })
                print(f"  rejected={type(exc).__name__}: {exc}", flush=True)
            # Checkpoint every completed/rejected batch so a transport/process
            # interruption never discards already validated, paid-for work.
            checkpoint_candidates = rank_representative_candidates(proposed, limit=args.limit)
            checkpoint = validation_payload(
                candidates=checkpoint_candidates, corpora=corpora, source_db=source_db,
                model=settings.model, budget=budget,
            )
            checkpoint["batchDiagnostics"] = list(diagnostics)
            write_validation_payload(args.output, checkpoint)
        candidates = rank_representative_candidates(proposed, limit=args.limit)
        model = settings.model
    payload = validation_payload(
        candidates=candidates, corpora=corpora, source_db=source_db,
        model=model, budget=budget,
    )
    if not args.structural_only:
        payload["batchDiagnostics"] = diagnostics
    destination = write_validation_payload(args.output, payload)
    print(f"Wrote {len(candidates)} MACHINE_PROPOSED / UNCONFIRMED candidates to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
