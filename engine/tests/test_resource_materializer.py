import json
from pathlib import Path

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.knowledge_base import TranslationHelpsKnowledgeBase
from tc_ai_bridge.resource_materializer import (
    materialize_book_checks, materialize_translation_words_links_index, ensure_resources_installed,
)
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import TranslationCoreProject


# Real chapter/verse content that exists in the bundled Titus tN/TWL slice
# (engine/resources/en/translationHelps/.../tn_TIT.tsv, twl_TIT.tsv) —
# these are the actual Door43 unfoldingWord v90 files committed to the repo,
# not a synthetic fixture, per the P0 acceptance criteria's "small real
# TN/TW resource slice" requirement.
SIMPLE_USFM = """\\id TIT
\\h Titus
\\toc1 The Letter to Titus
\\c 1
\\p
\\v 1 Paul, a servant of God.
\\v 2 in hope of eternal life.
\\c 2
\\v 1 But speak the things that fit sound doctrine.
"""


def _metadata(**overrides):
    value = {
        "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
        "projectName": "Titus review", "bibleName": "Test Bible",
    }
    value.update(overrides)
    return value


def _call(engine, method, params=None):
    request = EngineRequest(id="materializer-test", method=method, params=params or {})
    return engine.handle_request(request).to_dict()


def test_ensure_resources_installed_copies_bundled_snapshot_once(tmp_path):
    app_resources_root = tmp_path / "resources"
    ensure_resources_installed(app_resources_root)
    tn_dir = app_resources_root / "en" / "translationHelps" / "translationNotes"
    assert tn_dir.is_dir()
    versions = list(tn_dir.iterdir())
    assert versions, "expected at least one bundled translationNotes version folder"
    assert (versions[0] / "tn_TIT.tsv").is_file()

    # translationAcademy was NOT in this function's resource list before Phase 7
    # (see docs/BUILD_LOG.md) — a real gap, not an oversight in this test.
    ta_dir = app_resources_root / "en" / "translationHelps" / "translationAcademy"
    assert ta_dir.is_dir()
    assert list(ta_dir.iterdir()), "expected at least one bundled translationAcademy version folder"

    uhb = app_resources_root / "hbo" / "bibles" / "uhb" / "v3.0.0_unfoldingWord"
    ugnt = app_resources_root / "el-x-koine" / "bibles" / "ugnt" / "v0.34_unfoldingWord"
    for original_language in (uhb, ugnt):
        assert (original_language / "LICENSE.md").is_file()
        assert (original_language / "manifest.yaml").is_file()
        assert (original_language / "NOTICE.md").is_file()
        assert (original_language / "PROVENANCE.json").is_file()

    # Calling again must not touch (or duplicate/overwrite) an already-installed version.
    marker = versions[0] / "tn_TIT.tsv"
    original_bytes = marker.read_bytes()
    ensure_resources_installed(app_resources_root)
    assert marker.read_bytes() == original_bytes


def test_materialize_book_checks_produces_real_titus_entries(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    resources_root = tmp_path / "resources"

    result = materialize_book_checks(project_root, "tit", resources_root)

    assert result["translationNotes"]["status"] == "ready"
    assert result["translationNotes"]["checks"] > 0
    assert result["translationWords"]["status"] == "ready"
    assert result["translationWords"]["checks"] > 0

    tn_dir = project_root / ".apps" / "translationCore" / "index" / "translationNotes" / "tit"
    tw_dir = project_root / ".apps" / "translationCore" / "index" / "translationWords" / "tit"
    assert list(tn_dir.glob("*.json"))
    assert list(tw_dir.glob("*.json"))

    sample = json.loads(next(tn_dir.glob("*.json")).read_text(encoding="utf-8"))
    entry = sample[0]
    ctx = entry["contextId"]
    assert ctx["tool"] == "translationNotes"
    assert ctx["reference"]["bookId"] == "tit"
    assert ctx["reference"]["chapter"] and ctx["reference"]["verse"]
    assert entry["selections"] is False


def test_materialize_book_checks_is_idempotent(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    resources_root = tmp_path / "resources"

    first = materialize_book_checks(project_root, "tit", resources_root)
    second = materialize_book_checks(project_root, "tit", resources_root)

    assert first["translationNotes"]["checks"] == second["translationNotes"]["checks"]
    assert first["translationWords"]["checks"] == second["translationWords"]["checks"]


def test_materialize_book_checks_reports_unavailable_for_unreleased_book(tmp_path):
    # Some OT books (e.g. Isaiah) are not currently released in the bundled
    # English tN/TWL snapshot upstream — must report "unavailable", never a
    # fabricated "ready" with zero checks.
    result = materialize_book_checks(tmp_path / "project", "isa", tmp_path / "resources")
    assert result["translationNotes"]["status"] == "unavailable"
    assert result["translationNotes"]["checks"] == 0


def test_raw_import_defers_real_tn_tw_until_checks_and_then_surfaces_them(tmp_path):
    isolated = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=isolated)

    source = tmp_path / "57-TIT.usfm"
    source.write_text(SIMPLE_USFM, encoding="utf-8")

    result = engine.import_project(str(source), _metadata())
    project_path = Path(result["path"])

    capabilities = json.loads((project_path / ".bridge" / "import.json").read_text(encoding="utf-8"))["capabilities"]
    assert capabilities["translationNotes"] == "requires-resource-index"
    assert capabilities["translationWords"] == "requires-resource-index"

    response = _call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    assert response["success"] is True
    capabilities = json.loads((project_path / ".bridge" / "import.json").read_text(encoding="utf-8"))["capabilities"]
    assert capabilities["translationNotes"] == "ready"
    assert capabilities["translationWords"] == "ready"
    manifest = json.loads((project_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tc_en_check_version_translationNotes"]
    assert manifest["tc_en_check_version_translationWords"]
    categories = {f["category"] for f in response["findings"]}
    assert "translation_note" in categories or "translation_word" in categories


def test_materialize_translation_words_links_index_produces_resource_level_groups(tmp_path):
    """The real gap found while investigating Phase 7's ai.explain prerequisite (see
    docs/BUILD_LOG.md): knowledge_base.py's TWL reader expects a DIFFERENT,
    resource-level layout than materialize_book_checks() alone ever produced."""
    resources_root = tmp_path / "resources"
    ensure_resources_installed(resources_root)

    result = materialize_translation_words_links_index("tit", resources_root)

    assert result is not None
    assert result.checks > 0
    # Real term from the bundled Titus TWL slice (rc://*/tw/dict/bible/names/paul).
    paul_file = resources_root / "en" / "translationHelps" / "translationWordsLinks" / result.version / "names" / "groups" / "tit" / "paul.json"
    assert paul_file.is_file()
    entries = json.loads(paul_file.read_text(encoding="utf-8"))
    assert entries
    ctx = entries[0]["contextId"]
    assert ctx["reference"]["bookId"] == "tit"
    assert ctx["reference"]["chapter"] and ctx["reference"]["verse"]
    assert ctx["quoteString"]


def test_materialize_translation_words_links_index_is_idempotent(tmp_path):
    resources_root = tmp_path / "resources"
    ensure_resources_installed(resources_root)
    first = materialize_translation_words_links_index("tit", resources_root)
    second = materialize_translation_words_links_index("tit", resources_root)
    assert first.checks == second.checks
    assert first.groups == second.groups


def test_knowledge_base_twl_occurrences_reads_real_materialized_data_end_to_end(tmp_path):
    """Not just "the files got written" — confirms the actual consumer
    (TranslationHelpsKnowledgeBase.twl_occurrences, used by ai_client.py's
    evidence-gathering) can now read real data, closing the gap rather than
    just plausibly fixing it."""
    isolated = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=isolated)
    source = tmp_path / "57-TIT.usfm"
    source.write_text(
        "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n", encoding="utf-8",
    )
    result = engine.import_project(str(source), _metadata())
    # tN/tW/TWL materialization is deferred until the first checking preflight
    # for a raw import (see the "requires-resource-index" test above) — it
    # doesn't happen at import time.
    _call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    project = TranslationCoreProject(Path(result["path"]))
    kb = TranslationHelpsKnowledgeBase(project)

    occurrences = kb.twl_occurrences("paul")

    assert occurrences
    assert occurrences[0]["contextId"]["reference"]["bookId"] == "tit"
