"""The release version is declared in five places; they must not drift apart.

Release 0.12.0 bumped `package.json`, `tauri.conf.json` and `Cargo.toml` but left
`BRIDGE_VERSION` and `ENGINE_VERSION` on 0.11.0 (#170). Nothing caught it until a
frozen-pair smoke run failed at its version assertion, which is both late and easy
to miss: `scripts/smoke_sidecars.py` is `continue-on-error` in `release.yml`, so a
release can go green with a stale sidecar inside it.

`package.json` is the source of truth here because that is what the smoke script
already compares the frozen engine against.
"""
from __future__ import annotations

import json
import re

import pytest

from bridge_service import BRIDGE_VERSION
from greek_room_engine.engine import ENGINE_VERSION
from tests.support.paths import REPO_ROOT


def _package_json_version() -> str:
    data = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    return str(data["version"])


def test_engine_constants_match_package_json() -> None:
    """The two Python constants are what a frozen sidecar reports as its version."""
    expected = _package_json_version()
    assert BRIDGE_VERSION == expected, (
        f"BRIDGE_VERSION is {BRIDGE_VERSION!r} but package.json says {expected!r}. "
        "Bump engine/bridge_service.py in the same commit as the release bump."
    )
    assert ENGINE_VERSION == expected, (
        f"ENGINE_VERSION is {ENGINE_VERSION!r} but package.json says {expected!r}. "
        "Bump engine/greek_room_engine/engine.py in the same commit as the release bump."
    )


def test_shell_manifests_match_package_json() -> None:
    """A half-applied bump on the Rust side fails the frozen smoke just as hard."""
    expected = _package_json_version()

    tauri = json.loads(
        (REPO_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    assert str(tauri["version"]) == expected, (
        f"tauri.conf.json says {tauri['version']!r}, package.json says {expected!r}."
    )

    cargo_text = (REPO_ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    # The first top-level `version = "..."` in Cargo.toml is [package].version;
    # dependency versions all sit further down under their own tables.
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', cargo_text)
    assert match is not None, "No [package] version found in src-tauri/Cargo.toml"
    assert match.group(1) == expected, (
        f"Cargo.toml says {match.group(1)!r}, package.json says {expected!r}."
    )


@pytest.mark.parametrize("version", [BRIDGE_VERSION, ENGINE_VERSION])
def test_versions_are_plain_release_numbers(version: str) -> None:
    """Guards against a placeholder or a dirty suffix reaching a release build."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"{version!r} is not a bare MAJOR.MINOR.PATCH release version."
    )
