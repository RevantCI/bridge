"""Run only the engine tests your uncommitted changes could affect.

    python scripts/affected_tests.py            # work out what changed, run those tests
    python scripts/affected_tests.py --list     # just name them
    python scripts/affected_tests.py --since origin/main   # a whole branch, not just the working tree
    python scripts/affected_tests.py engine/tc_ai_bridge/usfm.py   # explicit paths

This is a **pre-check, not a gate**. The gate is the full suite that runs on every
push to `main` (#74 phase 3, narrowed on 2026-09-30: no nightly or weekly runs,
no CI-side selection -- the maintainer keeps the full run on push and wants the
fast pass locally). So it is allowed to be pragmatic where a CI gate could not
be: when it cannot reason about a change it says so and selects everything,
and when it misses something the push still catches it.

How the selection works, and where it stops:

- A changed test file selects itself.
- A changed Python module under `engine/` selects every test that imports it,
  directly or transitively, via a static `ast` import graph.
- A changed file it cannot reason about -- anything non-Python, or Python outside
  `engine/` -- is looked up by basename among the string literals in test files,
  because engine tests really do read `.ts`, `.svelte`, `.rs`, `.json` and `.md`
  files as text. If nothing references it, nothing is selected; if the basename
  is too generic to be meaningful, everything is.
- If the selection covers most of the suite anyway, it runs everything and says
  so, because a "selected" run that is 90% of the suite is just a slower full
  run with a worse name.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "engine"
TESTS = ENGINE / "tests"
# greek_room_engine keeps its own tests beside itself, and pyproject collects both.
EXTRA_TEST_ROOTS = [ENGINE / "greek_room_engine" / "tests"]

# Directories that are not ours to reason about: vendored upstream code, the
# virtualenv, build output.
SKIP_PARTS = {".venv", "vendor", "__pycache__", "build", "dist", "node_modules"}

# Above this share of the suite, selection has stopped being worth the words.
FULL_RUN_RATIO = 0.6

# A basename this short or this common tells us nothing about which test wants it.
GENERIC_BASENAMES = {"index.ts", "types.ts", "main.py", "__init__.py", "conftest.py",
                     "package.json", "tsconfig.json", "README.md"}


def _run(args: list[str]) -> str:
    done = subprocess.run(args, cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    return done.stdout if done.returncode == 0 else ""


def changed_files(since: str) -> list[Path]:
    """Paths the caller is about to commit (or, with --since, has already)."""
    names: set[str] = set()
    if since:
        names.update(_run(["git", "diff", "--name-only", f"{since}...HEAD"]).split("\n"))
    # Staged and unstaged, plus files git does not know about yet -- a brand new
    # test is exactly the thing you want run.
    names.update(_run(["git", "diff", "HEAD", "--name-only"]).split("\n"))
    for line in _run(["git", "status", "--porcelain", "--untracked-files=all"]).split("\n"):
        if line.startswith("?? "):
            names.add(line[3:].strip())
    return sorted({REPO / name.strip() for name in names if name.strip()})


def _module_name(path: Path) -> str | None:
    """`engine/tc_ai_bridge/usfm.py` -> `tc_ai_bridge.usfm`, the name imports use."""
    try:
        relative = path.resolve().relative_to(ENGINE)
    except ValueError:
        return None
    if relative.suffix != ".py":
        return None
    parts = list(relative.parts[:-1]) + [relative.stem]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _python_files() -> list[Path]:
    return [p for p in ENGINE.rglob("*.py")
            if not (SKIP_PARTS & set(p.parts)) and p.is_file()]


def _imports_of(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            # `from .tc_project import X` inside tc_ai_bridge -- resolve it to the
            # package this file lives in, or a relative import is invisible here.
            package = _module_name(path) or ""
            base = package.rsplit(".", node.level)[0] if "." in package else ""
            if node.module:
                base = f"{base}.{node.module}" if base else node.module
            if base:
                found.add(base)
                found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def build_reverse_graph() -> dict[str, set[str]]:
    """module name -> the modules that import it (one hop)."""
    reverse: dict[str, set[str]] = {}
    for path in _python_files():
        name = _module_name(path)
        if not name:
            continue
        for imported in _imports_of(path):
            reverse.setdefault(imported, set()).add(name)
    return reverse


def all_test_modules() -> set[str]:
    names = set()
    for root in [TESTS, *EXTRA_TEST_ROOTS]:
        if not root.is_dir():
            continue
        for path in root.rglob("test_*.py"):
            name = _module_name(path)
            if name:
                names.add(name)
    return names


def dependents(seed: str, reverse: dict[str, set[str]]) -> set[str]:
    """Everything that imports `seed`, directly or through anything else."""
    seen: set[str] = set()
    queue = [seed]
    while queue:
        current = queue.pop()
        for importer in reverse.get(current, ()):
            if importer not in seen:
                seen.add(importer)
                queue.append(importer)
    return seen


def tests_mentioning(basename: str) -> set[str]:
    """Tests that name this file in a string literal.

    Engine tests genuinely read `.ts`, `.svelte`, `.rs` and `.md` files as text,
    so a frontend or docs change can break one. Grepping the basename is the same
    check a human is told to do before deleting a file across layers.
    """
    if basename in GENERIC_BASENAMES or len(basename) < 5:
        return set()
    pattern = re.compile(re.escape(basename))
    hits = set()
    for root in [TESTS, *EXTRA_TEST_ROOTS]:
        if not root.is_dir():
            continue
        for path in root.rglob("test_*.py"):
            try:
                if pattern.search(path.read_text(encoding="utf-8")):
                    name = _module_name(path)
                    if name:
                        hits.add(name)
            except (OSError, UnicodeDecodeError):
                continue
    return hits


def select(paths: list[Path]) -> tuple[set[str], list[str]]:
    """Return (test module names, reasons). An empty reason list means a clean read."""
    reverse = build_reverse_graph()
    every_test = all_test_modules()
    selected: set[str] = set()
    reasons: list[str] = []

    for path in paths:
        name = _module_name(path)
        if name and name in every_test:
            selected.add(name)
            continue
        if name:
            selected |= dependents(name, reverse) & every_test
            continue
        # Not a Python module under engine/.
        try:
            relative = path.resolve().relative_to(REPO).as_posix()
        except ValueError:
            relative = path.name
        if path.suffix == ".py":
            # A script or tool outside engine/: tests may invoke it by path.
            selected |= tests_mentioning(path.name)
            continue
        mentioned = tests_mentioning(path.name)
        if mentioned:
            selected |= mentioned
        elif path.name in GENERIC_BASENAMES or len(path.name) < 5:
            reasons.append(f"{relative}: name too generic to trace")
            selected |= every_test
    return selected, reasons


def to_pytest_paths(modules: set[str]) -> list[str]:
    out = []
    for name in sorted(modules):
        out.append(str((ENGINE / Path(*name.split("."))).with_suffix(".py").relative_to(ENGINE)).replace("\\", "/"))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("paths", nargs="*", help="Explicit changed paths; defaults to your uncommitted work.")
    parser.add_argument("--since", default="", metavar="REF",
                        help="Also include everything committed since REF (e.g. origin/main).")
    parser.add_argument("--list", action="store_true", help="Print the selection instead of running it.")
    args, passthrough = parser.parse_known_args()

    paths = [Path(p) if Path(p).is_absolute() else REPO / p for p in args.paths]
    if not paths:
        paths = changed_files(args.since)
    if not paths:
        print("No changes found; nothing to run.")
        return 0

    inside = [p for p in paths if p.exists() or p.suffix]
    print("changed:")
    for path in inside:
        try:
            print(f"  {path.resolve().relative_to(REPO).as_posix()}")
        except ValueError:
            print(f"  {path}")

    selected, reasons = select(inside)
    every_test = all_test_modules()
    for reason in reasons:
        print(f"note: {reason}")

    if not selected:
        print("\nNo engine test imports or names anything that changed.")
        print("Nothing to run here — the full suite still runs on push to main.")
        return 0

    if len(selected) >= max(1, int(len(every_test) * FULL_RUN_RATIO)):
        print(f"\nselected {len(selected)} of {len(every_test)} test files — running the whole suite instead.")
        targets = ["tests/", "greek_room_engine/tests/"]
    else:
        targets = to_pytest_paths(selected)
        print(f"\nselected {len(targets)} of {len(every_test)} test files:")
        for target in targets:
            print(f"  {target}")

    if args.list:
        return 0

    command = [sys.executable, "-m", "pytest", *targets, *passthrough]
    print(f"\n$ {' '.join(command[1:])}\n", flush=True)
    return subprocess.run(command, cwd=ENGINE).returncode


if __name__ == "__main__":
    raise SystemExit(main())
