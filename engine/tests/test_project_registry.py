import json
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
