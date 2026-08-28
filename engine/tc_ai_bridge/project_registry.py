"""Persistent project discovery, identity, and duplicate classification.

The registry is deliberately separate from settings.json: project discovery must
remain recoverable even when preferences are reset, and it must never share a
write path with encrypted credentials.  Managed projects also carry a small
``.bridge/project.json`` identity file so moving the whole project does not turn
it into a new project.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REGISTRY_SCHEMA_VERSION = 1
IDENTITY_SCHEMA_VERSION = 1
_IDENTITY_PATH = Path(".bridge") / "project.json"
_IMPORT_PATH = Path(".bridge") / "import.json"
_LAZY_IMPORT_PATH = Path(".bridge") / "lazy-import.json"
_COLLECTION_PATH = Path(".bridge") / "collection.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def canonical_path_key(path: str | Path) -> str:
    """Return a comparison key that treats Windows path aliases consistently."""
    resolved = Path(path).expanduser().resolve(strict=False)
    return os.path.normcase(os.path.normpath(str(resolved)))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_fingerprint(root: Path, *, include_state: bool = True) -> str:
    """Hash a project/source tree deterministically without Bridge-local identity."""
    digest = hashlib.sha256()
    ignored = {_IDENTITY_PATH.as_posix(), ".bridge/collection.json"}
    paths = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda p: p.as_posix().lower())
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if relative in ignored or relative.startswith(".bridge-import-"):
            continue
        if not include_state and relative.startswith(".apps/"):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def source_fingerprints(preview: dict[str, Any]) -> dict[str, str]:
    """Return exact-source fingerprints keyed by canonical book id."""
    result: dict[str, str] = {}
    for book in preview.get("books", []):
        if not isinstance(book, dict):
            continue
        book_id = str(book.get("bookId") or "").lower()
        source = Path(str(book.get("sourceFile") or ""))
        if not book_id or not source.exists():
            continue
        try:
            result[book_id] = _sha256_file(source) if source.is_file() else _tree_fingerprint(source)
        except OSError:
            continue
    return result


def collection_fingerprint(fingerprints: dict[str, str]) -> str:
    if not fingerprints:
        return ""
    payload = "\n".join(f"{book}:{fingerprints[book]}" for book in sorted(fingerprints))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProjectRegistry:
    def __init__(self, path: Path, managed_root: Path):
        self.path = Path(path)
        self.managed_root = Path(managed_root).resolve(strict=False)
        self._data = self._load()
        self._managed_discovered = False
        self._dirty = False

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schemaVersion": REGISTRY_SCHEMA_VERSION, "projects": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(value, dict) or not isinstance(value.get("projects"), list):
                raise ValueError("registry root is invalid")
            return {"schemaVersion": REGISTRY_SCHEMA_VERSION, "projects": value["projects"]}
        except (OSError, ValueError, json.JSONDecodeError):
            # Keep the damaged evidence for diagnostics, but do not let it prevent
            # managed-project discovery from rebuilding a usable registry.
            try:
                corrupt = self.path.with_name(f"{self.path.stem}.corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}{self.path.suffix}")
                os.replace(self.path, corrupt)
            except OSError:
                pass
            return {"schemaVersion": REGISTRY_SCHEMA_VERSION, "projects": []}

    def _save(self) -> None:
        _write_json_atomic(self.path, self._data)
        self._dirty = False

    def _is_managed(self, path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(self.managed_root)
            return True
        except ValueError:
            return False

    def _find(self, *, path: Path | None = None, project_id: str = "") -> dict[str, Any] | None:
        path_key = canonical_path_key(path) if path is not None else ""
        for entry in self._data["projects"]:
            if not isinstance(entry, dict):
                continue
            if project_id and entry.get("projectId") == project_id:
                return entry
            if path_key and entry.get("pathKey") == path_key:
                return entry
        return None

    @staticmethod
    def _project_metadata(path: Path) -> dict[str, str]:
        manifest = _read_json(path / "manifest.json")
        lazy = _read_json(path / _LAZY_IMPORT_PATH)
        collection = _read_json(path / _COLLECTION_PATH)
        project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
        target = manifest.get("target_language") if isinstance(manifest.get("target_language"), dict) else {}
        resource = manifest.get("resource") if isinstance(manifest.get("resource"), dict) else {}
        bridge_project = manifest.get("bridge_project") if isinstance(manifest.get("bridge_project"), dict) else {}
        book_id = str(project.get("id") or lazy.get("bookId") or "").lower()
        book_name = str(project.get("name") or lazy.get("bookName") or book_id.upper())
        metadata = lazy.get("metadata") if isinstance(lazy.get("metadata"), dict) else {}
        return {
            "bookId": book_id,
            "bookName": book_name,
            "targetLanguageId": str(target.get("id") or metadata.get("languageId") or ""),
            "targetLanguage": str(target.get("name") or metadata.get("languageName") or ""),
            "projectName": str(bridge_project.get("name") or collection.get("projectName") or metadata.get("projectName") or book_name),
            "bibleName": str(resource.get("name") or collection.get("bibleName") or metadata.get("bibleName") or ""),
            "resourceId": str(resource.get("id") or metadata.get("resourceId") or ""),
        }

    @staticmethod
    def _legacy_collection_id(collection: dict[str, Any]) -> str:
        """Group schema-1 collections without merging separate import runs."""
        projects = collection.get("projects")
        if not isinstance(projects, list) or len(projects) < 2:
            return ""
        paths = sorted(
            canonical_path_key(str(entry.get("path") or ""))
            for entry in projects
            if isinstance(entry, dict) and entry.get("path")
        )
        if len(paths) < 2:
            return ""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "bridge-legacy-collection:" + "\n".join(paths)))

    @staticmethod
    def _source_fingerprint(path: Path, identity: dict[str, Any]) -> str:
        remembered = str(identity.get("sourceFingerprint") or "")
        if remembered:
            return remembered
        imported = _read_json(path / _IMPORT_PATH)
        source = imported.get("source") if isinstance(imported.get("source"), dict) else {}
        value = str(source.get("sha256") or "")
        if value:
            return value
        manifest = _read_json(path / "manifest.json")
        bridge_import = manifest.get("bridge_import") if isinstance(manifest.get("bridge_import"), dict) else {}
        value = str(bridge_import.get("sourceSha256") or "")
        if value:
            return value
        lazy = _read_json(path / _LAZY_IMPORT_PATH)
        source_copy = str(lazy.get("sourceCopy") or "")
        copied = path / source_copy
        if source_copy and copied.is_file():
            return _sha256_file(copied)
        try:
            return _tree_fingerprint(path)
        except OSError:
            return ""

    def register(
        self,
        path: str | Path,
        *,
        touch: bool = False,
        source_fingerprint: str = "",
        project_id: str = "",
        collection_id: str = "",
        save: bool = True,
    ) -> dict[str, Any]:
        project_path = Path(path).resolve(strict=False)
        managed = self._is_managed(project_path)
        identity_path = project_path / _IDENTITY_PATH
        identity = _read_json(identity_path)
        project_id = str(project_id or identity.get("projectId") or "")
        collection = _read_json(project_path / _COLLECTION_PATH)
        collection_id = str(collection_id or identity.get("collectionId") or collection.get("collectionId") or "")
        if not collection_id:
            collection_id = self._legacy_collection_id(collection)
        if not project_id:
            project_id = str(uuid.uuid4())
        if managed:
            created_at = str(identity.get("createdAt") or _utc_now())
            new_identity = {
                "schemaVersion": IDENTITY_SCHEMA_VERSION,
                "projectId": project_id,
                "collectionId": collection_id,
                "sourceFingerprint": source_fingerprint or self._source_fingerprint(project_path, identity),
                "createdAt": created_at,
            }
            if new_identity != identity:
                _write_json_atomic(identity_path, new_identity)
                self._dirty = True
            identity = new_identity

        entry = self._find(path=project_path, project_id=project_id)
        is_new = entry is None
        if is_new:
            entry = {"projectId": project_id, "createdAt": _utc_now(), "lastOpenedAt": ""}
            self._data["projects"].append(entry)
        snapshot = None if is_new else dict(entry)
        metadata = self._project_metadata(project_path)
        entry.update({
            "projectId": project_id,
            "collectionId": collection_id,
            "path": str(project_path),
            "pathKey": canonical_path_key(project_path),
            "managed": managed,
            "missing": not project_path.exists(),
            "sourceFingerprint": source_fingerprint or self._source_fingerprint(project_path, identity),
            **metadata,
        })
        if touch:
            entry["lastOpenedAt"] = _utc_now()
        if is_new or entry != snapshot:
            self._dirty = True
        if save:
            self._save()
        return dict(entry)

    def list_projects(self, *, refresh_managed: bool = True, collapse_collections: bool = False) -> list[dict[str, Any]]:
        self.managed_root.mkdir(parents=True, exist_ok=True)
        if refresh_managed or not self._managed_discovered:
            # Only NEW managed directories go through register()'s full
            # metadata/fingerprint resolution (several file reads each,
            # plus a source-fingerprint hash the first time a project has
            # no cached one yet) — an already-known project is skipped
            # here entirely. Before this, every list_projects() call
            # (i.e. every time the project picker or dashboard opened)
            # re-registered EVERY managed project from scratch regardless
            # of whether anything had changed; with a real multi-book
            # collection (dozens to 66 sibling folders, each imported as
            # its own managed project) that turned an instant list into a
            # many-second stall on every open, purely from redundant work
            # repeated on projects that hadn't changed since the last
            # call. A project whose metadata genuinely changes after
            # first discovery (e.g. a lazy sibling gets materialized) is
            # re-registered for real when it's actually opened
            # (open_project() -> register(..., touch=True)), which is the
            # only place metadata can meaningfully change anyway.
            known_path_keys = {
                entry.get("pathKey") for entry in self._data["projects"] if isinstance(entry, dict)
            }
            for child in self.managed_root.iterdir():
                if not child.is_dir() or child.name.startswith(".bridge-import-"):
                    continue
                if canonical_path_key(child) in known_path_keys:
                    continue
                if (child / "manifest.json").is_file() or (child / _LAZY_IMPORT_PATH).is_file():
                    self.register(child, save=False)
            self._managed_discovered = True
        for entry in self._data["projects"]:
            if not isinstance(entry, dict):
                continue
            missing = not Path(str(entry.get("path") or "")).exists()
            if entry.get("missing") != missing:
                entry["missing"] = missing
                self._dirty = True
        if self._dirty:
            self._save()
        result = [dict(value) for value in self._data["projects"] if isinstance(value, dict)]
        result.sort(key=lambda value: str(value.get("lastOpenedAt") or ""), reverse=True)
        result.sort(key=lambda value: bool(value.get("missing")))
        return self._collapse_collections(result) if collapse_collections else result

    @staticmethod
    def _collapse_collections(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse multi-book collections into one representative row.

        ``entries`` is already sorted (non-missing first, most-recently-opened
        first), so the first entry seen per ``collectionId`` is the right
        representative to keep.
        """
        counts: dict[str, int] = {}
        representative_index: dict[str, int] = {}
        result: list[dict[str, Any]] = []
        for entry in entries:
            collection_id = str(entry.get("collectionId") or "")
            if not collection_id:
                result.append(entry)
                continue
            counts[collection_id] = counts.get(collection_id, 0) + 1
            if collection_id not in representative_index:
                representative_index[collection_id] = len(result)
                result.append(entry)
        for collection_id, index in representative_index.items():
            result[index]["bookCount"] = counts[collection_id]
        return result

    def group_entries(self, project_id: str) -> list[dict[str, Any]]:
        """Return the entry for ``project_id`` plus any siblings sharing its collectionId."""
        target = self._find(project_id=project_id)
        if target is None:
            return []
        collection_id = str(target.get("collectionId") or "")
        if not collection_id:
            return [dict(target)]
        return [
            dict(entry) for entry in self._data["projects"]
            if isinstance(entry, dict) and entry.get("collectionId") == collection_id
        ]

    def forget(self, project_id: str) -> bool:
        before = len(self._data["projects"])
        target = self._find(project_id=project_id)
        collection_id = str(target.get("collectionId") or "") if target else ""
        self._data["projects"] = [
            entry for entry in self._data["projects"]
            if not isinstance(entry, dict) or (
                entry.get("projectId") != project_id
                and (not collection_id or entry.get("collectionId") != collection_id)
            )
        ]
        changed = len(self._data["projects"]) != before
        if changed:
            self._save()
        return changed

    def get(self, project_id: str) -> dict[str, Any] | None:
        entry = self._find(project_id=project_id)
        return dict(entry) if entry is not None else None

    def classify(self, preview: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        projects = self.list_projects(refresh_managed=False)
        source_by_book = source_fingerprints(preview)
        combined = dict(preview.get("metadata") or {})
        combined.update(metadata or {})
        language_id = str(combined.get("languageId") or "").casefold()
        bible_name = str(combined.get("bibleName") or "").strip().casefold()
        matches: list[dict[str, Any]] = []
        exact_books: set[str] = set()
        missing_exact_books: set[str] = set()
        possible_books: set[str] = set()
        overlapping_books: set[str] = set()
        exact_books_by_group: dict[str, set[str]] = {}
        preview_books = {
            str(book.get("bookId") or "").lower()
            for book in preview.get("books", []) if isinstance(book, dict)
        }
        for entry in projects:
            book_id = str(entry.get("bookId") or "").lower()
            if book_id not in preview_books:
                continue
            source_fp = source_by_book.get(book_id, "")
            exact = bool(source_fp and source_fp == entry.get("sourceFingerprint"))
            logical = bool(
                book_id
                and language_id
                and language_id == str(entry.get("targetLanguageId") or "").casefold()
                and (
                    not bible_name
                    or bible_name == str(entry.get("bibleName") or "").strip().casefold()
                )
            )
            if not exact and not logical:
                continue
            overlapping_books.add(book_id)
            group_id = (
                f"collection:{entry.get('collectionId')}"
                if entry.get("collectionId")
                else f"project:{entry.get('projectId')}"
            )
            if exact and not entry.get("missing", False):
                exact_books.add(book_id)
                exact_books_by_group.setdefault(group_id, set()).add(book_id)
            elif exact:
                missing_exact_books.add(book_id)
            elif not exact:
                possible_books.add(book_id)
            matches.append({
                "match": "exact" if exact else "possible",
                "reason": "sourceFingerprint" if exact else "bookLanguageBible",
                "groupId": group_id,
                "projectId": entry.get("projectId"),
                "collectionId": entry.get("collectionId"),
                "path": entry.get("path"),
                "bookId": entry.get("bookId"),
                "bookName": entry.get("bookName"),
                "projectName": entry.get("projectName"),
                "bibleName": entry.get("bibleName"),
                "lastOpenedAt": entry.get("lastOpenedAt"),
                "missing": entry.get("missing", False),
            })
        exact_match_group_id = next((
            group_id for group_id, books in exact_books_by_group.items()
            if books == preview_books
        ), "")
        if preview_books and exact_match_group_id:
            classification = "exactDuplicate"
        elif overlapping_books:
            classification = "partialOverlap" if len(preview_books) > 1 else "possibleDuplicate"
        else:
            classification = "new"
        return {
            "classification": classification,
            "matches": matches,
            "inputBookCount": len(preview_books),
            "exactBookCount": len(exact_books),
            "missingExactBookCount": len(missing_exact_books),
            "possibleBookCount": len(possible_books),
            "overlapBookCount": len(overlapping_books),
            "matchingGroupCount": len({match["groupId"] for match in matches}),
            "exactMatchGroupId": exact_match_group_id,
            "sourceFingerprints": source_by_book,
            "collectionFingerprint": collection_fingerprint(source_by_book),
        }
