import json
import hashlib
import shutil
from pathlib import Path

from tc_ai_bridge.project_registry import ProjectRegistry


def _project(root: Path, name: str = "rut") -> Path:
    path = root / name
    (path / name).mkdir(parents=True)
    (path / "manifest.json").write_text(json.dumps({
        "project": {"id": name, "name": name.upper()},
        "target_language": {"id": "tam", "name": "Tamil"},
        "resource": {"id": "ult", "name": "Test Bible"},
        "bridge_project": {"name": "Community review"},
    }), encoding="utf-8")
    (path / name / "1.json").write_text('{"1": "text"}', encoding="utf-8")
    return path


def _preview(root: Path, books: list[tuple[str, str, str]]) -> dict:
    source = root / "source"
    source.mkdir(parents=True, exist_ok=True)
    values = []
    for book_id, book_name, content in books:
        path = source / f"{book_id}.usfm"
        path.write_text(content, encoding="utf-8")
        values.append({"bookId": book_id, "bookName": book_name, "sourceFile": str(path)})
    return {"books": values, "metadata": {}}


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _metadata(language_id: str = "tam", bible_name: str = "Test Bible") -> dict[str, str]:
    return {"languageId": language_id, "bibleName": bible_name}


def test_managed_identity_survives_rename_and_repairs_registry_path(tmp_path):
    managed = tmp_path / "projects"
    original = _project(managed)
    registry = ProjectRegistry(tmp_path / "project-registry.json", managed)
    first = registry.register(original, touch=True)

    moved = managed / "renamed-rut"
    original.rename(moved)
    listed = registry.list_projects()

    assert len(listed) == 1
    assert listed[0]["projectId"] == first["projectId"]
    assert listed[0]["path"] == str(moved.resolve())
    assert listed[0]["missing"] is False
    identity = json.loads((moved / ".bridge" / "project.json").read_text(encoding="utf-8"))
    assert identity["projectId"] == first["projectId"]


def test_external_missing_project_can_be_located_without_changing_identity(tmp_path):
    managed = tmp_path / "managed"
    external = _project(tmp_path / "external")
    registry = ProjectRegistry(tmp_path / "project-registry.json", managed)
    first = registry.register(external)
    relocated = tmp_path / "relocated" / "rut"
    relocated.parent.mkdir()
    shutil.move(str(external), relocated)

    assert registry.list_projects()[0]["missing"] is True
    repaired = registry.register(relocated, project_id=first["projectId"])

    assert repaired["projectId"] == first["projectId"]
    assert repaired["path"] == str(relocated.resolve())
    assert len(registry.list_projects()) == 1


def test_corrupt_registry_is_quarantined_and_managed_projects_are_rediscovered(tmp_path):
    managed = tmp_path / "projects"
    project = _project(managed)
    registry_path = tmp_path / "project-registry.json"
    registry_path.write_text("not-json", encoding="utf-8")

    registry = ProjectRegistry(registry_path, managed)
    listed = registry.list_projects()

    assert len(listed) == 1
    assert listed[0]["path"] == str(project.resolve())
    assert list(tmp_path.glob("project-registry.corrupt-*.json"))


def test_legacy_collection_entries_receive_one_stable_group_identity(tmp_path):
    managed = tmp_path / "projects"
    titus = _project(managed, "tit")
    philemon = _project(managed, "phm")
    collection = {
        "schemaVersion": 1,
        "projectName": "Legacy NT",
        "projects": [
            {"path": str(titus), "bookId": "tit"},
            {"path": str(philemon), "bookId": "phm"},
        ],
    }
    for project in (titus, philemon):
        bridge = project / ".bridge"
        bridge.mkdir()
        (bridge / "collection.json").write_text(json.dumps(collection), encoding="utf-8")

    registry = ProjectRegistry(tmp_path / "project-registry.json", managed)
    listed = registry.list_projects()

    assert len(listed) == 2
    assert listed[0]["collectionId"]
    assert {entry["collectionId"] for entry in listed} == {listed[0]["collectionId"]}


def test_exact_single_book_duplicate_reports_content_reason_and_counts(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    project = _project(tmp_path / "managed", "tit")
    registry.register(project, source_fingerprint=_fingerprint("same source"))

    result = registry.classify(
        _preview(tmp_path / "incoming", [("tit", "Titus", "same source")]),
        _metadata(),
    )

    assert result["classification"] == "exactDuplicate"
    assert result["exactBookCount"] == result["overlapBookCount"] == 1
    assert result["missingExactBookCount"] == 0
    assert result["possibleBookCount"] == 0
    assert result["matchingGroupCount"] == 1
    assert result["exactMatchGroupId"].startswith("project:")
    assert result["matches"][0]["reason"] == "sourceFingerprint"


def test_same_book_metadata_with_different_content_is_only_possible(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    project = _project(tmp_path / "managed", "tit")
    registry.register(project, source_fingerprint=_fingerprint("old source"))

    result = registry.classify(
        _preview(tmp_path / "incoming", [("tit", "Titus", "new source")]),
        _metadata(),
    )

    assert result["classification"] == "possibleDuplicate"
    assert result["exactBookCount"] == 0
    assert result["missingExactBookCount"] == 0
    assert result["possibleBookCount"] == 1
    assert result["exactMatchGroupId"] == ""
    assert result["matches"][0]["reason"] == "bookLanguageBible"


def test_same_display_name_with_different_canonical_book_is_new(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    project = _project(tmp_path / "managed", "tit")
    manifest_path = project / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["project"]["name"] = "Shared name"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry.register(project, source_fingerprint=_fingerprint("old source"))

    result = registry.classify(
        _preview(tmp_path / "incoming", [("phm", "Shared name", "new source")]),
        _metadata(),
    )

    assert result["classification"] == "new"
    assert result["matches"] == []


def test_metadata_overlap_requires_language_and_supplied_bible_to_match(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    project = _project(tmp_path / "managed", "tit")
    registry.register(project, source_fingerprint=_fingerprint("old source"))
    preview = _preview(tmp_path / "incoming", [("tit", "Titus", "new source")])

    assert registry.classify(preview, _metadata(language_id="eng"))["classification"] == "new"
    assert registry.classify(preview, _metadata(bible_name="Other Bible"))["classification"] == "new"
    normalized = registry.classify(preview, _metadata(language_id="TAM", bible_name="  test bible "))
    assert normalized["classification"] == "possibleDuplicate"


def test_missing_exact_project_warns_but_does_not_block_reimport(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    project = _project(tmp_path / "managed", "tit")
    registered = registry.register(project, source_fingerprint=_fingerprint("same source"))
    moved = tmp_path / "elsewhere" / "tit"
    moved.parent.mkdir()
    shutil.move(project, moved)

    result = registry.classify(
        _preview(tmp_path / "incoming", [("tit", "Titus", "same source")]),
        _metadata(),
    )

    assert result["classification"] == "possibleDuplicate"
    assert result["exactBookCount"] == 0
    assert result["missingExactBookCount"] == 1
    assert result["exactMatchGroupId"] == ""
    assert result["matches"] == [{
        "match": "exact",
        "reason": "sourceFingerprint",
        "groupId": f"project:{registered['projectId']}",
        "projectId": registered["projectId"],
        "collectionId": "",
        "path": str(project.resolve()),
        "bookId": "tit",
        "bookName": "TIT",
        "projectName": "Community review",
        "bibleName": "Test Bible",
        "lastOpenedAt": "",
        "missing": True,
    }]


def test_one_existing_collection_covering_every_book_is_exact_duplicate(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    sources = {"tit": "titus source", "phm": "philemon source"}
    for book_id, content in sources.items():
        registry.register(
            _project(tmp_path / "managed", book_id),
            source_fingerprint=_fingerprint(content),
            collection_id="collection-one",
        )

    result = registry.classify(
        _preview(tmp_path / "incoming", [
            ("tit", "Titus", sources["tit"]),
            ("phm", "Philemon", sources["phm"]),
        ]),
        _metadata(),
    )

    assert result["classification"] == "exactDuplicate"
    assert result["exactBookCount"] == 2
    assert result["exactMatchGroupId"] == "collection:collection-one"
    assert {match["groupId"] for match in result["matches"]} == {"collection:collection-one"}


def test_exact_books_scattered_across_projects_do_not_block_collection_import(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    sources = {"tit": "titus source", "phm": "philemon source"}
    for index, (book_id, content) in enumerate(sources.items()):
        registry.register(
            _project(tmp_path / "managed" / str(index), book_id),
            source_fingerprint=_fingerprint(content),
        )

    result = registry.classify(
        _preview(tmp_path / "incoming", [
            ("tit", "Titus", sources["tit"]),
            ("phm", "Philemon", sources["phm"]),
        ]),
        _metadata(),
    )

    assert result["classification"] == "partialOverlap"
    assert result["exactBookCount"] == 2
    assert result["overlapBookCount"] == 2
    assert result["matchingGroupCount"] == 2
    assert result["exactMatchGroupId"] == ""


def test_partial_collection_and_metadata_overlap_remain_non_blocking(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    registry.register(
        _project(tmp_path / "managed", "tit"),
        source_fingerprint=_fingerprint("titus source"),
        collection_id="old-collection",
    )
    registry.register(
        _project(tmp_path / "managed", "phm"),
        source_fingerprint=_fingerprint("old philemon"),
        collection_id="old-collection",
    )

    result = registry.classify(
        _preview(tmp_path / "incoming", [
            ("tit", "Titus", "titus source"),
            ("phm", "Philemon", "changed philemon"),
            ("rut", "Ruth", "new ruth"),
        ]),
        _metadata(),
    )

    assert result["classification"] == "partialOverlap"
    assert result["inputBookCount"] == 3
    assert result["exactBookCount"] == 1
    assert result["possibleBookCount"] == 1
    assert result["overlapBookCount"] == 2
    assert result["exactMatchGroupId"] == ""


def test_list_projects_does_not_rewrite_files_when_nothing_changed(tmp_path, monkeypatch):
    import tc_ai_bridge.project_registry as registry_module

    calls: list[Path] = []
    original_write = registry_module._write_json_atomic

    def counting_write(path, value):
        calls.append(path)
        original_write(path, value)

    monkeypatch.setattr(registry_module, "_write_json_atomic", counting_write)

    managed = tmp_path / "managed"
    registry = ProjectRegistry(tmp_path / "registry.json", managed)
    project_path = _project(managed, "rut")
    registry.register(project_path, touch=True)
    calls.clear()

    registry.list_projects()
    registry.list_projects()

    assert calls == [], "re-scanning an unchanged managed project must not rewrite any JSON file"

    # Sanity check the counter isn't simply broken: a real change still writes.
    registry.register(project_path, touch=True)
    assert calls, "touching a project should still persist the change"


def test_list_projects_skips_full_rescan_of_already_known_projects(tmp_path, monkeypatch):
    """The bug this fixes: every list_projects() call used to re-run
    register()'s full metadata/fingerprint resolution (several file reads
    per project) for EVERY managed project, every time -- fine for a
    handful of projects, but with a real multi-book collection (dozens to
    66 sibling folders, each its own managed project) that turned every
    dashboard/import-screen open into redundant work proportional to the
    whole library, repeated forever. Only a project not yet in the
    registry should hit _project_metadata at all."""
    import tc_ai_bridge.project_registry as registry_module

    calls = 0
    original_metadata = registry_module.ProjectRegistry._project_metadata

    def counting_metadata(path):
        nonlocal calls
        calls += 1
        return original_metadata(path)

    monkeypatch.setattr(registry_module.ProjectRegistry, "_project_metadata", staticmethod(counting_metadata))

    managed = tmp_path / "managed"
    for book_id in ("rut", "tit", "phm"):
        _project(managed, book_id)

    registry = ProjectRegistry(tmp_path / "registry.json", managed)
    registry.list_projects()
    first_call_count = calls
    assert first_call_count == 3  # one per newly-discovered managed project

    registry.list_projects()
    registry.list_projects()
    assert calls == first_call_count, "already-known managed projects must not be re-scanned on repeat listings"

    # A genuinely new managed project still gets discovered.
    _project(managed, "jas")
    listed = registry.list_projects()
    assert calls == first_call_count + 1
    assert {entry["bookId"] for entry in listed} == {"rut", "tit", "phm", "jas"}


def test_list_projects_collapses_collections_only_when_requested(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    registry.register(_project(tmp_path / "managed", "tit"), collection_id="collection-a")
    registry.register(_project(tmp_path / "managed", "phm"), collection_id="collection-a")
    registry.register(_project(tmp_path / "managed", "rut"))

    flat = registry.list_projects()
    assert len(flat) == 3
    assert all("bookCount" not in entry for entry in flat)

    collapsed = registry.list_projects(collapse_collections=True)
    assert len(collapsed) == 2
    assert any(entry["bookId"] == "rut" and "bookCount" not in entry for entry in collapsed)
    collection_entry = next(entry for entry in collapsed if entry.get("collectionId") == "collection-a")
    assert collection_entry["bookCount"] == 2


def test_group_entries_returns_collection_siblings(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json", tmp_path / "managed")
    tit = registry.register(_project(tmp_path / "managed", "tit"), collection_id="collection-b")
    registry.register(_project(tmp_path / "managed", "phm"), collection_id="collection-b")
    solo = registry.register(_project(tmp_path / "managed", "rut"))

    siblings = registry.group_entries(tit["projectId"])
    assert {entry["bookId"] for entry in siblings} == {"tit", "phm"}

    solo_group = registry.group_entries(solo["projectId"])
    assert len(solo_group) == 1
    assert solo_group[0]["bookId"] == "rut"
