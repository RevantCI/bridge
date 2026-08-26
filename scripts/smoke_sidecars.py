"""Packaged sidecar smoke test.

Build both executables first, then pass the frozen bridge-engine path.  The
test creates a temporary translationCore-shaped project whose source USFM has
balanced markers but duplicate/missing verses, so the legacy USFM_BALANCE
regex cannot make this test pass accidentally.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _fixture_project(root: Path) -> Path:
    project = root / "titus"
    _write_json(project / "manifest.json", {
        "project": {"id": "tit", "name": "Titus"},
        "target_language": {"id": "eng", "name": "English"},
        "tc_version": "8",
    })
    _write_json(project / "tit" / "1.json", {
        "1": "ପ୍ରଥମ ପଦ।",
        "3": "ତୃତୀୟ ପଦ।",
    })
    _write_json(project / "tit" / "2.json", {
        "1": "Paul sent greetings to Titus his true son.",
        "4": "Titus is a beloved child in the common faith.",
        "7": "In everything show yourself an example, Tituss my son.",
    })
    _write_json(project / ".apps" / "translationCore" / "alignmentData" / "tit" / "1.json", {
        "1": {
            "alignments": [
                {
                    "topWords": [
                        {
                            "word": "Παῦλος", "strong": "G39720", "lemma": "Παῦλος",
                            "morph": "Gr,N,,,,,NMS,", "occurrence": 1, "occurrences": 1,
                        },
                    ],
                    "bottomWords": [
                        {"word": "ପ୍ରଥମ", "occurrence": 1, "occurrences": 1, "type": "bottomWord"},
                    ],
                },
                {
                    "topWords": [
                        {
                            "word": "δοῦλος", "strong": "G14010", "lemma": "δοῦλος",
                            "morph": "Gr,N,,,,,NMS,", "occurrence": 1, "occurrences": 1,
                        },
                    ],
                    "bottomWords": [],
                },
            ],
            "wordBank": [
                {"word": "ପଦ", "occurrence": 1, "occurrences": 1, "type": "bottomWord"},
            ],
        },
        "3": {
            "alignments": [{
                "topWords": [{
                    "word": "λόγος", "strong": "G30560", "lemma": "λόγος",
                    "morph": "Gr,N,,,,,NMS,", "occurrence": 1, "occurrences": 1,
                }],
                "bottomWords": [
                    {"word": "ତୃତୀୟ", "occurrence": 1, "occurrences": 1, "type": "bottomWord"},
                    {"word": "ପଦ", "occurrence": 1, "occurrences": 1, "type": "bottomWord"},
                ],
            }],
            "wordBank": [],
        },
    })
    _write_json(project / ".apps" / "translationCore" / "alignmentData" / "tit" / "2.json", {
        "1": {"alignments": [], "wordBank": []},
        "4": {"alignments": [], "wordBank": []},
        "7": {"alignments": [], "wordBank": []},
    })
    (project / "tit.usfm").write_text(
        "\\id TIT\n\\h Titus\n\\toc1 The Letter to Titus\n\\c 1\n\\p\n"
        "\\v 1 ପ୍ରଥମ ପଦ।\n"
        "\\v 1 ନକଲ ପଦ ସଂଖ୍ୟା।\n"
        "\\v 3 ତୃତୀୟ ପଦ; ଦ୍ୱିତୀୟ ପଦ ନାହିଁ।\n",
        encoding="utf-8",
    )
    return project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", type=Path, help="Path to frozen bridge-engine executable")
    parser.add_argument("--import-source", type=Path, help="Optional real USFM/Paratext folder to benchmark")
    parser.add_argument("--max-import-seconds", type=float, default=10.0)
    args = parser.parse_args()
    engine = args.engine.resolve()
    extension = engine.suffix if sys.platform == "win32" else ""
    helper = engine.with_name(f"bridge-usfm-checker{extension}")
    if not engine.is_file() or not helper.is_file():
        raise SystemExit(f"Expected sibling executables: {engine} and {helper}")

    version = subprocess.run(
        [str(helper), "--version"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    if version.returncode != 0 or "vendored-18ddcf0" not in version.stdout:
        raise SystemExit(f"Helper health check failed: {version.stderr or version.stdout}")

    with tempfile.TemporaryDirectory(prefix="bridge-frozen-smoke-") as temp:
        project = _fixture_project(Path(temp))
        process_env = os.environ.copy()
        process_env["LOCALAPPDATA"] = str(Path(temp) / "app-data")
        process = subprocess.Popen(
            [str(engine)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", env=process_env,
        )
        frames: queue.Queue[dict] = queue.Queue()

        def read_stdout() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    frames.put(json.loads(line))
                except json.JSONDecodeError:
                    continue

        threading.Thread(target=read_stdout, daemon=True).start()

        def request(request_id: str, method: str, params: dict, timeout: float = 30) -> dict:
            assert process.stdin is not None
            process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    response = frames.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if response.get("id") == request_id:
                    return response
            raise SystemExit(f"Request {request_id} timed out")

        try:
            info = request("info", "engine.info", {})
            if not info.get("success"):
                raise SystemExit(f"Request info failed: {info}")
            if info.get("result", {}).get("bridgeVersion") != "0.8.0-beta.10":
                raise SystemExit(f"Frozen engine version is stale or inconsistent: {info}")
            wildebeest = (
                info.get("result", {})
                .get("greekRoom", {})
                .get("adapters", {})
                .get("wildebeest", {})
            )
            if not wildebeest.get("usingRealEngine"):
                raise SystemExit(
                    "Frozen engine is using the Wildebeest mock fallback: "
                    f"{wildebeest}"
                )
            names = (
                info.get("result", {})
                .get("greekRoom", {})
                .get("adapters", {})
                .get("names", {})
            )
            if not names.get("available") or not names.get("usingRealEngine"):
                raise SystemExit(
                    "Frozen engine is missing real Uroman/Smart Edit Distance: "
                    f"{names}"
                )

            raw_source = Path(temp) / "57-TIT.usfm"
            raw_source.write_text(
                "\\id TIT\n\\h Titus\n\\c 1\n\\v 1 Paul, a servant of God.\n",
                encoding="utf-8",
            )
            raw_import = request("original-language-import", "project.import", {
                "path": str(raw_source),
                "destinationRoot": str(Path(temp) / "original-language-projects"),
                "metadata": {
                    "languageId": "eng",
                    "languageName": "English",
                    "languageDirection": "ltr",
                    "projectName": "Frozen original-language smoke",
                    "bibleName": "Test Bible",
                },
            })
            original_resource = raw_import.get("result", {}).get("originalLanguageResource", {})
            if (
                not raw_import.get("success")
                or original_resource.get("resourceId") != "ugnt"
                or original_resource.get("version") != "0.34"
                or original_resource.get("commit") != "fc95b2b8aad08bb65ab54628ab685413a1139e97"
            ):
                raise SystemExit(f"Frozen UGNT resource provenance failed: {raw_import}")
            raw_alignment = request(
                "original-language-alignment", "alignment.get", {"chapter": "1", "verse": "1"},
            )
            raw_top_tokens = raw_alignment.get("result", {}).get("topTokens", [])
            if (
                not raw_alignment.get("success")
                or not raw_alignment.get("result", {}).get("sourceAvailable")
                or len(raw_top_tokens) != 17
                or raw_top_tokens[0].get("word") != "Παῦλος"
            ):
                raise SystemExit(f"Frozen UGNT token initialization failed: {raw_alignment}")

            if args.import_source:
                started_at = time.perf_counter()
                imported = request("import", "project.import", {
                    "path": str(args.import_source.resolve()),
                    "destinationRoot": str(Path(temp) / "imported"),
                    "metadata": {
                        "languageId": "tam",
                        "languageName": "Tamil",
                        "languageDirection": "ltr",
                        "projectName": "Frozen import benchmark",
                        "bibleName": "Tamil Bible",
                    },
                }, timeout=max(30.0, args.max_import_seconds + 10.0))
                elapsed = time.perf_counter() - started_at
                if not imported.get("success"):
                    raise SystemExit(f"Frozen import failed: {imported}")
                projects = imported.get("result", {}).get("importedProjects", [])
                if len(projects) != 66:
                    raise SystemExit(f"Frozen import returned {len(projects)} projects, expected 66")
                if elapsed >= args.max_import_seconds:
                    raise SystemExit(
                        f"Frozen import took {elapsed:.2f}s, limit is {args.max_import_seconds:.2f}s"
                    )
                print(f"Frozen 66-book import passed in {elapsed:.2f}s.")

            opened = request("open", "project.open", {"path": str(project)})
            if not opened.get("success"):
                raise SystemExit(f"Request open failed: {opened}")
            project_id = opened.get("result", {}).get("projectId")
            if not project_id:
                raise SystemExit(f"Frozen project.open did not assign a stable project id: {opened}")
            listed = request("project-list", "project.list", {})
            registered = listed.get("result", {}).get("projects", [])
            if not listed.get("success") or not any(
                item.get("projectId") == project_id and Path(item.get("path", "")) == project
                for item in registered
            ):
                raise SystemExit(f"Frozen project registry did not return the opened project: {listed}")
            duplicate = request("project-duplicate", "project.inspectImport", {"path": str(project)})
            assessment = duplicate.get("result", {}).get("duplicates", {})
            if (
                assessment.get("classification") != "exactDuplicate"
                or assessment.get("inputBookCount") != 1
                or assessment.get("exactBookCount") != 1
                or assessment.get("missingExactBookCount") != 0
                or assessment.get("matchingGroupCount", 0) < 1
                or not assessment.get("exactMatchGroupId", "").startswith("project:")
                or not any(
                    match.get("match") == "exact" and match.get("reason") == "sourceFingerprint"
                    for match in assessment.get("matches", [])
                )
            ):
                raise SystemExit(f"Frozen duplicate classification failed: {duplicate}")

            versification_detect = request("versification-detect", "versification.detect", {})
            if (
                not versification_detect.get("success")
                or not versification_detect["result"].get("bestSchema")
            ):
                raise SystemExit(
                    f"Frozen versification detection failed: {versification_detect}"
                )
            versification_org_ref = request(
                "versification-org-ref",
                "versification.orgRef",
                {"chapter": "1", "verse": "1", "schema": "eng"},
            )
            if (
                not versification_org_ref.get("success")
                or versification_org_ref["result"].get("orgRef") != "TIT 1:1"
            ):
                raise SystemExit(
                    f"Frozen versification orgRef failed: {versification_org_ref}"
                )
            versification_back_map = request(
                "versification-back-map",
                "versification.backVersificationMap",
                {"schema": "eng"},
            )
            if not versification_back_map.get("success"):
                raise SystemExit(
                    f"Frozen versification backVersificationMap failed: {versification_back_map}"
                )

            names_check = request(
                "names-check",
                "verse.runChecks",
                {"chapter": "2", "verse": "7", "checks": ["names"]},
            )
            names_findings = names_check.get("findings", [])
            if (
                not names_check.get("success")
                or not any(
                    finding.get("engine") == "names"
                    and finding.get("original_text") == "Tituss"
                    and finding.get("suggested_replacement") == "Titus"
                    for finding in names_findings
                )
            ):
                raise SystemExit(
                    f"Frozen names/transliteration check missed Titus/Tituss: {names_check}"
                )

            alignment = request("alignment-get", "alignment.get", {"chapter": "1", "verse": "1"})
            if not alignment.get("success") or not alignment["result"].get("sourceAvailable"):
                raise SystemExit(f"Frozen alignment source was unavailable: {alignment}")
            context = alignment["result"]
            realigned = request("alignment-realign", "alignment.realign", {
                "chapter": "1", "verse": "1",
                "topIds": [token["id"] for token in context["topTokens"]],
                "bottomIds": [token["id"] for token in context["bottomTokens"]],
                "expectedOriginal": context["alignment"],
            })
            if not realigned.get("success") or not realigned["result"].get("canComplete"):
                raise SystemExit(f"Frozen many-to-many alignment failed: {realigned}")
            completed = request(
                "alignment-complete", "alignment.complete", {"chapter": "1", "verse": "1"},
            )
            if not completed.get("success") or completed["result"].get("completionState") != "completed":
                raise SystemExit(f"Frozen alignment completion failed: {completed}")

            corpus_summary = request("corpus-stats-summary", "alignment.corpusStats.summary", {})
            if not corpus_summary.get("success") or corpus_summary["result"].get("versesScanned") != 1:
                raise SystemExit(f"Frozen corpus stats summary failed: {corpus_summary}")
            corpus_for_verse = request(
                "corpus-stats-for-verse", "alignment.corpusStats.forVerse", {"chapter": "1", "verse": "1"},
            )
            if not corpus_for_verse.get("success"):
                raise SystemExit(f"Frozen corpus stats forVerse failed: {corpus_for_verse}")
            pairs = corpus_for_verse["result"].get("pairs", [])
            if not pairs or pairs[0].get("jointCount") != 1 or pairs[0].get("translationProbability") != 1.0:
                raise SystemExit(f"Frozen corpus stats forVerse returned unexpected data: {corpus_for_verse}")

            # No API key is configured in this smoke test (no real network call is made or
            # needed) — this exists to confirm ai_client.py/alignment_engine.py's new imports
            # (apply_proposal, validate_preparation_proposal) and alignment_reliability.py are
            # actually bundled and importable inside the FROZEN executable, not just in source
            # mode. A missing/broken bundle would surface as an internal_error or a crash here,
            # not the expected clean ai_error.
            ai_propose = request(
                "ai-propose-no-key", "alignment.aiPropose", {"chapter": "1", "verse": "1"},
            )
            if ai_propose.get("success") or ai_propose.get("error", {}).get("code") != "ai_error":
                raise SystemExit(f"Frozen alignment.aiPropose did not fail cleanly with ai_error: {ai_propose}")

            # Same reasoning as ai-propose-no-key above: confirms ai.explain's imports
            # (knowledge_base.py, the now-bundled translationAcademy resource tree) are
            # real and importable inside the frozen executable. This fixture project has
            # no application-storage resources/ folder of its own (it's hand-built, not
            # created via project.import's real materialization flow), so
            # TranslationHelpsKnowledgeBase's constructor legitimately raises
            # knowledge_base_error before ai_client.py ever reaches its own missing-API-key
            # check — both are real, clean failures proving the bundle is intact; only an
            # internal_error/crash would indicate a real packaging gap.
            ai_explain = request(
                "ai-explain-no-key", "ai.explain", {"chapter": "1", "verse": "1"},
            )
            if ai_explain.get("success") or ai_explain.get("error", {}).get("code") not in ("ai_error", "knowledge_base_error"):
                raise SystemExit(f"Frozen ai.explain did not fail cleanly: {ai_explain}")

            # A developer machine may or may not have the companion running.
            # Either a well-formed live state or the connector's clean unavailable
            # error proves the frozen import/dispatch path is intact.
            paratext_state = request("paratext-state", "paratext.getState", {})
            if paratext_state.get("success"):
                paratext_result = paratext_state.get("result", {})
                if not paratext_result.get("connected") or not paratext_result.get("project_id"):
                    raise SystemExit(f"Frozen paratext.getState returned invalid live state: {paratext_state}")
            elif paratext_state.get("error", {}).get("code") != "paratext_connector_error":
                raise SystemExit(f"Frozen paratext.getState did not fail cleanly: {paratext_state}")

            # Real, meaningful check: this actually spawns the bundled logos_bridge.ps1
            # from under sys._MEIPASS (see bridge-engine.spec's logos_connector datas
            # entry) — a missing/broken bundle would show up as a different failure
            # shape (a spawn/file-not-found error) than the real "Logos isn't installed"
            # COM error this asserts on.
            logos_state = request("logos-not-installed", "logos.getState", {}, timeout=25)
            if logos_state.get("success") or logos_state.get("error", {}).get("code") != "logos_connector_error":
                raise SystemExit(f"Frozen logos.getState did not fail cleanly: {logos_state}")
            if "not registered" not in logos_state["error"]["message"].lower() and "logos" not in logos_state["error"]["message"].lower():
                raise SystemExit(f"Frozen logos.getState failed for an unexpected reason (bundle may be missing): {logos_state}")

            aligned_path = Path(temp) / "tit-aligned.usfm"
            exported = request(
                "alignment-export", "export.aligned", {"outputPath": str(aligned_path)},
            )
            if not exported.get("success") or "\\zaln-s" not in aligned_path.read_text(encoding="utf-8"):
                raise SystemExit(f"Frozen aligned-USFM export failed: {exported}")
            undone = request("alignment-undo", "alignment.undo", {
                "chapter": "1", "verse": "1",
                "expectedOriginal": completed["result"]["alignment"],
            })
            if not undone.get("success") or undone["result"].get("status") != "partial":
                raise SystemExit(f"Frozen alignment undo failed: {undone}")

            started = request("start", "checks.start", {
                "scope": "chapter", "chapters": ["1"], "checks": ["usfm"],
            })
            if not started.get("success"):
                raise SystemExit(f"Request start failed: {started}")
            job_id = started["result"]["jobId"]

            # Reproduce the desktop's first-open request order. ReviewPanel sends
            # a Greek-Room-only live check immediately after checks.start; if that
            # request waits for the tN/tW/USFM/names preparation lock, the
            # synchronous stdio loop cannot even read status/list requests behind
            # it. The deterministic source test holds that lock explicitly; this
            # frozen gate proves the release binary contains the non-blocking path.
            live_started = time.monotonic()
            live_review = request(
                "live-greek-room-while-checking", "verse.runChecks",
                {"chapter": "1", "verse": "1", "checks": ["greekroom"]}, timeout=5,
            )
            live_elapsed = time.monotonic() - live_started
            if not live_review.get("success") or live_elapsed >= 5:
                raise SystemExit(
                    "Frozen live Greek Room request blocked the dispatcher during preparation: "
                    f"elapsed={live_elapsed:.2f}s response={live_review}"
                )

            review_started = time.monotonic()
            review = request(
                "review-while-checking", "check.listForVerse",
                {"chapter": "1", "verse": "1"}, timeout=5,
            )
            review_elapsed = time.monotonic() - review_started
            review_state = review.get("result", {}).get("state")
            if (
                not review.get("success")
                or review_state not in {"ready", "preparing"}
                or review_elapsed >= 5
            ):
                raise SystemExit(
                    "Frozen review request blocked the dispatcher during checking: "
                    f"elapsed={review_elapsed:.2f}s response={review}"
                )
            responsive_status = request(
                "status-after-review", "checks.status", {"jobId": job_id}, timeout=5,
            )
            if not responsive_status.get("success"):
                raise SystemExit(
                    "Frozen status request was blocked behind translation-help loading: "
                    f"{responsive_status}"
                )

            snapshot = started["result"]
            deadline = time.monotonic() + 180
            attempt = 0
            while snapshot["state"] not in {"succeeded", "failed", "cancelled"}:
                if time.monotonic() >= deadline:
                    raise SystemExit(f"Frozen background job timed out: {snapshot}")
                time.sleep(0.1)
                attempt += 1
                status = request(f"status-{attempt}", "checks.status", {"jobId": job_id})
                if not status.get("success"):
                    raise SystemExit(f"Request status failed: {status}")
                snapshot = status["result"]

            if snapshot["state"] != "succeeded":
                raise SystemExit(f"Frozen background job failed: {snapshot}")
            check_types = {
                finding["check_type"]
                for result in snapshot["results"].values()
                for finding in result.get("findings", [])
            }
            if "usfm.duplicate_verse_number" not in check_types:
                raise SystemExit(f"Frozen checker missed duplicate verse: {sorted(check_types)}")
            if not any("missing_verses" in value for value in check_types):
                raise SystemExit(f"Frozen checker missed absent verse: {sorted(check_types)}")
        finally:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)

    print(
        "Frozen sidecar smoke test passed: real Wildebeest/Uroman loaded; "
        "pinned UGNT source tokens, versification, names/transliteration, "
        "alignment statistics/proposal packaging, "
        "AI explain packaging, desktop connectors, project registry/duplicate import, "
        "first-open live-review responsiveness, alignment/export/undo, and "
        "duplicate/missing-verse checks succeeded."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
