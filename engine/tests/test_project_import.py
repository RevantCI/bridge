import json
import zipfile
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.project_import import import_source, inspect_import
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import ProjectError, TranslationCoreProject


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
        "languageId": "eng",
        "languageName": "English",
        "languageDirection": "ltr",
        "projectName": "Titus review",
        "bibleName": "Test Bible",
    }
    value.update(overrides)
    return value


def _call(engine, method, params=None):
    request = EngineRequest(id="import-test", method=method, params=params or {})
    return engine.handle_request(request).to_dict()


def test_inspect_usfm_reports_books_and_missing_language(tmp_path):
    source = tmp_path / "57-TIT.usfm"
    source.write_text(SIMPLE_USFM, encoding="utf-8")

    preview = inspect_import(source)

    assert preview["kind"] == "usfm"
    assert preview["books"] == [{
        "bookId": "tit",
        "bookName": "Titus",
        "sourceFile": str(source.resolve()),
        "verseCount": 3,
        "hasAlignments": False,
    }]
    assert "languageId" in preview["missingFields"]
    assert "languageName" in preview["missingFields"]
    assert preview["metadata"]["bibleName"] == "The Letter to Titus"


def test_import_usfm_creates_tc_compatible_normalized_project(tmp_path):
    source = tmp_path / "57-TIT.sfm"
    source.write_text(SIMPLE_USFM, encoding="utf-8")

    result = import_source(source, tmp_path / "projects", _metadata())
    project_path = Path(result["primaryProjectPath"])
    project = TranslationCoreProject(project_path)

    assert project.summary.target_language == "English"
    assert project.chapters() == ["1", "2"]
    assert project.target_verse_text("1", "1") == "Paul, a servant of God."
    verse = project.load_verse_alignment("1", "1")
    assert verse.alignments == []
    assert [token.word for token in verse.word_bank] == ["Paul", "a", "servant", "of", "God"]
    assert (project_path / "tit.usfm").read_bytes() == source.read_bytes()

    manifest = json.loads((project_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["resource"]["name"] == "Test Bible"
    assert manifest["bridge_import"]["resourceIndexStatus"] == "required"
    provenance = json.loads((project_path / ".bridge" / "import.json").read_text(encoding="utf-8"))
    assert provenance["capabilities"]["translationNotes"] == "requires-resource-index"
    assert provenance["capabilities"]["wordAlignment"] == "ready-for-alignment"


def test_import_collection_creates_one_book_project_per_usfm(tmp_path):
    source = tmp_path / "ParatextProject"
    source.mkdir()
    (source / "57TIT.SFM").write_text(SIMPLE_USFM, encoding="utf-8")
    (source / "58PHM.SFM").write_text(
        "\\id PHM\n\\h Philemon\n\\c 1\n\\v 1 Paul, a prisoner of Christ Jesus.\n",
        encoding="utf-8",
    )

    preview = inspect_import(source)
    assert preview["kind"] == "usfmCollection"
    assert {book["bookId"] for book in preview["books"]} == {"tit", "phm"}

    result = import_source(source, tmp_path / "projects", _metadata(projectName="Whole NT"))
    assert {project["bookId"] for project in result["projects"]} == {"tit", "phm"}
    for item in result["projects"]:
        assert TranslationCoreProject(item["path"]).chapters() == ["1"] or item["bookId"] == "tit"


def test_basic_usfm3_alignment_is_preserved(tmp_path):
    source = tmp_path / "57-TIT.usfm"
    source.write_text(
        "\\id TIT\n\\h Titus\n\\c 1\n\\v 1 "
        "\\zaln-s |x-strong=\"G39720\" x-lemma=\"Παῦλος\" x-morph=\"Gr,N,,,,,NMS,\" "
        "x-occurrence=\"1\" x-occurrences=\"1\" x-content=\"Παῦλος\"\\*"
        "\\w Paul|x-occurrence=\"1\" x-occurrences=\"1\"\\w*\\zaln-e\\* came.\n",
        encoding="utf-8",
    )

    result = import_source(source, tmp_path / "projects", _metadata())
    project = TranslationCoreProject(result["primaryProjectPath"])
    alignment = project.load_verse_alignment("1", "1")

    assert project.target_verse_text("1", "1") == "Paul came."
    assert alignment.alignments[0].top_words[0].word == "Παῦλος"
    assert alignment.alignments[0].bottom_words[0].word == "Paul"
    assert [word.word for word in alignment.word_bank] == ["came"]


def test_tc_archive_import_preserves_check_indexes(tmp_path):
    source_project = tmp_path / "source-project"
    alignment = source_project / ".apps" / "translationCore" / "alignmentData" / "tit"
    index = source_project / ".apps" / "translationCore" / "index" / "translationNotes" / "tit"
    target = source_project / "tit"
    alignment.mkdir(parents=True)
    index.mkdir(parents=True)
    target.mkdir()
    (source_project / "manifest.json").write_text(json.dumps({
        "project": {"id": "tit", "name": "Titus"},
        "target_language": {"id": "eng", "name": "English", "direction": "ltr"},
        "resource": {"id": "ult", "name": "Unlocked Literal Text"},
    }), encoding="utf-8")
    (alignment / "1.json").write_text('{"1":{"alignments":[],"wordBank":[]}}', encoding="utf-8")
    (target / "1.json").write_text('{"1":"Text"}', encoding="utf-8")
    (index / "grammar.json").write_text('[{"contextId":{"tool":"translationNotes"}}]', encoding="utf-8")

    archive_path = tmp_path / "project.tcore"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in source_project.rglob("*"):
            if path.is_file():
                archive.write(path, Path("inside") / path.relative_to(source_project))

    result = import_source(archive_path, tmp_path / "projects", _metadata())
    imported = Path(result["primaryProjectPath"])
    assert (imported / ".apps" / "translationCore" / "index" / "translationNotes" / "tit" / "grammar.json").exists()


def test_archive_path_traversal_is_rejected(tmp_path):
    archive_path = tmp_path / "unsafe.tcore"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"project": {"id": "tit", "name": "Titus"}}))
        archive.writestr("../escape.txt", "no")

    with pytest.raises(ProjectError, match="unsafe path"):
        import_source(archive_path, tmp_path / "projects", _metadata())


def test_bridge_import_protocol_opens_primary_project(tmp_path):
    source = tmp_path / "TIT.usfm"
    source.write_text(SIMPLE_USFM, encoding="utf-8")
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))

    preview = _call(engine, "project.inspectImport", {"path": str(source)})
    assert preview["success"] is True
    result = _call(engine, "project.import", {"path": str(source), "metadata": _metadata()})

    assert result["success"] is True
    assert result["result"]["bookId"] == "tit"
    assert result["result"]["targetLanguageId"] == "eng"
    assert result["result"]["projectName"] == "Titus review"
    assert result["result"]["bibleName"] == "Test Bible"
    assert result["result"]["chapters"] == ["1", "2"]
    assert Path(result["result"]["path"]).is_relative_to(tmp_path / "projects")


def test_verse_bridge_import_and_check_does_not_crash(tmp_path):
    source = tmp_path / "TIT.usfm"
    source.write_text("\\id TIT\n\\c 1\n\\v 3-4 A bridged verse.\n", encoding="utf-8")
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    imported = _call(engine, "project.import", {"path": str(source), "metadata": _metadata()})
    assert imported["success"] is True

    checked = _call(engine, "verse.runChecks", {"chapter": "1", "verse": "3-4", "checks": ["local"]})
    assert checked["success"] is True
