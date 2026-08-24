"""
Tests for the Phase 7 translationAcademy bundling + knowledge_base.py fix
(see docs/DEVELOPER_HANDOFF.md). translationAcademy was never bundled before
this pass; once it was (a real 2.2MB, 728-file download of the real
Door43 unfoldingWord/en_ta v90 tag, not a synthetic fixture), reading it
turned out to hit exactly the same bug class every other vendored/bundled
integration in this project has hit: knowledge_base.py's TA-reading code
assumed a flat "<identifier>.md" file shape (correct for translationWords,
confirmed by the earlier P0 acceptance tests) but real TA articles are
DIRECTORIES (checking/accuracy-check/{title.md,sub-title.md,01.md}), not
flat files — found only by actually downloading and inspecting the real
content, not by reading documentation.
"""
import json
from pathlib import Path

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.knowledge_base import TranslationHelpsKnowledgeBase
from tc_ai_bridge.resource_materializer import ensure_resources_installed
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import TranslationCoreProject


def _metadata(**overrides):
    value = {
        "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
        "projectName": "Titus review", "bibleName": "Test Bible",
    }
    value.update(overrides)
    return value


def _call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="ta-test", method=method, params=params or {})).to_dict()


def test_translation_academy_is_bundled_with_the_matching_version_tag(tmp_path):
    resources_root = tmp_path / "resources"
    ensure_resources_installed(resources_root)
    ta_dir = resources_root / "en" / "translationHelps" / "translationAcademy" / "v90_unfoldingWord"
    assert ta_dir.is_dir()
    assert (ta_dir / "checking" / "accuracy-check" / "01.md").is_file()
    assert (ta_dir / "checking" / "accuracy-check" / "title.md").is_file()
    assert (ta_dir / "LICENSE.md").is_file()


def _real_knowledge_base(tmp_path) -> TranslationHelpsKnowledgeBase:
    isolated = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=isolated)
    source = tmp_path / "57-TIT.usfm"
    source.write_text(
        "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n", encoding="utf-8",
    )
    result = engine.import_project(str(source), _metadata())
    # tN/tW materialization (which also pins tc_en_check_version_translationNotes,
    # the manifest field ta_articles()/resolve('translationAcademy') matches its
    # own version against) is deferred until the first checking preflight.
    _call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    project = TranslationCoreProject(Path(result["path"]))
    return TranslationHelpsKnowledgeBase(project)


def test_ta_articles_reads_a_real_nested_directory_article(tmp_path):
    kb = _real_knowledge_base(tmp_path)

    items = kb.ta_articles("accuracy-check")

    assert items
    item = items[0]
    assert item.kind == "translationAcademy"
    assert "Accuracy" in item.title  # real title.md content, not the raw "01" filename stem
    assert "accurate" in item.content.lower()
    assert item.identifier == "accuracy-check"
    assert item.authoritative is True


def test_ta_articles_returns_nothing_for_an_unknown_identifier_rather_than_crashing(tmp_path):
    kb = _real_knowledge_base(tmp_path)
    assert kb.ta_articles("not-a-real-ta-article-slug") == []


def test_global_checking_evidence_reads_real_directory_based_articles(tmp_path):
    kb = _real_knowledge_base(tmp_path)

    items = kb.global_checking_evidence()

    assert items
    identifiers = {item.identifier for item in items}
    # All 13 checking-category identifiers hardcoded in global_checking_evidence()
    # are real, confirmed slugs in the actual v90 content, not a guess.
    assert "accuracy-check" in identifiers
    assert "alignment-tool" in identifiers
    for item in items:
        assert item.content.strip()
        assert item.kind == "translationAcademyChecking"
