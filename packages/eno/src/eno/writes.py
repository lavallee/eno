"""Write operations against a vault — create new notes, append to existing ones.

Designed for agents (MCP-spoken sessions) to file content into the vault
while the path-safety net keeps them out of `.git`, `.eno`, `.obsidian`, etc.

`create_note` enforces a minimal frontmatter contract per the AGENTS.md
convention: LLM-authored notes get `origin: llm` and an `author: '[[X]]'`
wikilink so future hygiene/garden passes never have to guess provenance.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .views import WriteResult

SYSTEM_DIRS = frozenset({".eno", ".git", ".obsidian", ".trash"})


def _safe_vault_path(vault: Path, rel_path: str) -> Path | None:
    """Resolve `rel_path` inside `vault`; return None if it escapes the vault
    or lands inside a protected system directory."""
    if not rel_path or rel_path.startswith("/"):
        return None
    if ".." in Path(rel_path).parts:
        return None
    full = (vault / rel_path).resolve()
    try:
        rel = full.relative_to(vault.resolve())
    except ValueError:
        return None
    if any(p in SYSTEM_DIRS for p in rel.parts):
        return None
    return full


def _today_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _default_frontmatter(*, author: str | None = None) -> dict:
    fm: dict = {"origin": "llm", "created": _today_iso(), "updated": _today_iso()}
    if author:
        fm["author"] = f"[[{author}]]"
    return fm


def _resolve_author(explicit: str | None) -> str | None:
    return explicit or os.environ.get("ENO_AGENT_NAME") or None


def create_note(
    vault: Path,
    rel_path: str,
    body: str,
    *,
    frontmatter: dict | None = None,
    overwrite: bool = False,
    author: str | None = None,
) -> WriteResult:
    if not rel_path.endswith(".md"):
        rel_path = rel_path + ".md"
    full = _safe_vault_path(vault, rel_path)
    if full is None:
        return WriteResult(
            path=rel_path,
            ok=False,
            error="invalid path (escapes vault or lands in a system dir)",
        )
    if full.exists() and not overwrite:
        return WriteResult(
            path=rel_path,
            ok=False,
            error="note exists; pass overwrite=True or use append_to_note",
        )

    fm = (
        dict(frontmatter)
        if frontmatter is not None
        else _default_frontmatter(author=_resolve_author(author))
    )
    if "title" not in fm:
        fm["title"] = full.stem
    # Normalize to ensure we always have updated stamped if not provided
    fm.setdefault("updated", _today_iso())
    if author and "author" not in fm:
        fm["author"] = f"[[{author}]]"

    fm_yaml = yaml.safe_dump(
        fm,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10**9,
    ).rstrip()
    raw = (
        f"---\n{fm_yaml}\n---\n\n"
        f"# {fm['title']}\n\n"
        f"{body.strip()}\n"
        if body.strip()
        else f"---\n{fm_yaml}\n---\n\n# {fm['title']}\n"
    )

    full.parent.mkdir(parents=True, exist_ok=True)
    try:
        full.write_text(raw, encoding="utf-8")
    except OSError as e:
        return WriteResult(path=rel_path, ok=False, error=f"write failed: {e}")
    return WriteResult(path=rel_path, ok=True, note="created")


def append_to_note(
    vault: Path,
    rel_path: str,
    content: str,
    *,
    under_heading: str | None = None,
) -> WriteResult:
    if not rel_path.endswith(".md"):
        rel_path = rel_path + ".md"
    full = _safe_vault_path(vault, rel_path)
    if full is None:
        return WriteResult(
            path=rel_path,
            ok=False,
            error="invalid path (escapes vault or lands in a system dir)",
        )
    if not full.exists():
        return WriteResult(path=rel_path, ok=False, error="note not found")

    try:
        raw = full.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return WriteResult(path=rel_path, ok=False, error=f"read failed: {e}")

    if under_heading is None:
        new_raw = raw.rstrip() + "\n\n" + content.strip() + "\n"
        msg = "appended at end"
    else:
        result = _insert_under_heading(raw, under_heading, content)
        if result is None:
            return WriteResult(
                path=rel_path,
                ok=False,
                error=f"heading not found: {under_heading!r}",
            )
        new_raw = result
        msg = f"inserted under {under_heading!r}"

    try:
        full.write_text(new_raw, encoding="utf-8")
    except OSError as e:
        return WriteResult(path=rel_path, ok=False, error=f"write failed: {e}")
    return WriteResult(path=rel_path, ok=True, note=msg)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*```")


def _insert_under_heading(raw: str, heading: str, content: str) -> str | None:
    """Insert `content` immediately under the matching heading, before the
    next heading at same-or-higher level (or end of file).

    Heading match is exact on `'#'-count + text` after stripping. Code fences
    are tracked so we don't match `# X` inside a fenced block.
    """
    target = _HEADING_RE.match(heading.strip())
    if not target:
        return None
    target_level = len(target.group(1))
    target_text = target.group(2).strip()

    lines = raw.splitlines()
    in_fence = False
    insert_at: int | None = None
    next_heading_at: int | None = None

    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2).strip()
        if insert_at is None and level == target_level and text == target_text:
            insert_at = i + 1
            continue
        if insert_at is not None and level <= target_level:
            next_heading_at = i
            break

    if insert_at is None:
        return None

    end = next_heading_at if next_heading_at is not None else len(lines)
    # Trim trailing blank lines from the section so the new content goes right
    # after the existing prose, not after a stretch of empty lines.
    j = end
    while j > insert_at and lines[j - 1].strip() == "":
        j -= 1

    out_lines = (
        lines[:j]
        + [""]
        + content.strip().splitlines()
        + [""]
        + lines[j:]
    )
    out = "\n".join(out_lines)
    return out + ("\n" if not out.endswith("\n") else "")
