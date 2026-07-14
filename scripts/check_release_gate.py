#!/usr/bin/env python3
"""Release gate: every package version in the workspace must agree.

All eno packages (and the Obsidian plugin manifest) move in lockstep — see
RELEASING.md. This script is dependency-free (stdlib only) so CI can run it
with a bare `python` before `uv sync`. Exits non-zero on any mismatch.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (label, file, regex capturing the version in group 1)
PYPROJECT_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.M)
INIT_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.M)

SOURCES: list[tuple[str, Path, re.Pattern[str]]] = [
    ("eno/pyproject", ROOT / "packages/eno/pyproject.toml", PYPROJECT_RE),
    ("eno/__init__", ROOT / "packages/eno/src/eno/__init__.py", INIT_RE),
    ("eno-mcp/pyproject", ROOT / "packages/eno-mcp/pyproject.toml", PYPROJECT_RE),
    ("eno-mcp/__init__", ROOT / "packages/eno-mcp/src/eno_mcp/__init__.py", INIT_RE),
    ("eno-service/pyproject", ROOT / "packages/eno-service/pyproject.toml", PYPROJECT_RE),
    ("eno-service/__init__", ROOT / "packages/eno-service/src/eno_service/__init__.py", INIT_RE),
]


def _find(label: str, path: Path, pattern: re.Pattern[str]) -> str | None:
    try:
        m = pattern.search(path.read_text(encoding="utf-8"))
    except OSError as e:
        print(f"  ! {label}: cannot read {path} ({e})")
        return None
    if not m:
        print(f"  ! {label}: no version found in {path}")
        return None
    return m.group(1)


def main() -> int:
    versions: dict[str, str] = {}
    ok = True

    for label, path, pattern in SOURCES:
        v = _find(label, path, pattern)
        if v is None:
            ok = False
        else:
            versions[label] = v

    # Plugin manifest (JSON).
    manifest = ROOT / "packages/eno-plugin/manifest.json"
    try:
        versions["eno-plugin/manifest"] = json.loads(
            manifest.read_text(encoding="utf-8")
        )["version"]
    except (OSError, KeyError, json.JSONDecodeError) as e:
        print(f"  ! eno-plugin/manifest: cannot read version ({e})")
        ok = False

    distinct = set(versions.values())
    for label, v in versions.items():
        print(f"  {label}: {v}")

    if len(distinct) > 1:
        print(f"\nFAIL: versions disagree: {sorted(distinct)}")
        return 1
    if not ok:
        print("\nFAIL: one or more versions could not be read")
        return 1

    print(f"\nOK: all packages at {distinct.pop()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
