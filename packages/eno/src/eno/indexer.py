"""Walk the vault, parse changed notes, write to sqlite. Idempotent and incremental on mtime."""

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from .config import index_path, state_path
from .db import open_index
from .parser import ParsedNote, parse_note
from .schema import SCHEMA_VERSION

# Directories we never walk into.
SKIP_DIRS = {".obsidian", ".git", ".eno", ".trash", "node_modules"}


@dataclass
class IndexStats:
    seen: int = 0
    parsed: int = 0
    skipped_unchanged: int = 0
    deleted: int = 0
    links_resolved: int = 0
    links_broken: int = 0
    elapsed_s: float = 0.0


def index_vault(vault: Path, *, full: bool = False) -> IndexStats:
    start = time.monotonic()
    stats = IndexStats()
    db = open_index(index_path(vault))
    try:
        existing: dict[str, float] = dict(db.execute("SELECT path, mtime FROM notes").fetchall())
        seen_paths: set[str] = set()

        for md_path in _walk_vault(vault):
            rel = md_path.relative_to(vault).as_posix()
            seen_paths.add(rel)
            stats.seen += 1
            try:
                mtime = md_path.stat().st_mtime
            except OSError:
                continue

            if not full and rel in existing and abs(existing[rel] - mtime) < 1e-6:
                stats.skipped_unchanged += 1
                continue

            try:
                raw = md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            note = parse_note(rel, raw)
            _upsert_note(db, note, mtime)
            stats.parsed += 1

        # Detect deletions
        for old_path in set(existing) - seen_paths:
            db.execute("DELETE FROM notes WHERE path = ?", (old_path,))
            stats.deleted += 1

        resolved, broken = _resolve_links(db)
        stats.links_resolved = resolved
        stats.links_broken = broken

        db.commit()
    finally:
        db.close()

    stats.elapsed_s = time.monotonic() - start
    _write_state(vault, stats)
    return stats


def _walk_vault(vault: Path):
    """Yield .md files under vault, skipping system dirs and any dotfile dir at any depth."""
    for path in vault.rglob("*.md"):
        rel_parts = path.relative_to(vault).parts[:-1]
        if any(p in SKIP_DIRS or p.startswith(".") for p in rel_parts):
            continue
        yield path


def _upsert_note(db: sqlite3.Connection, note: ParsedNote, mtime: float) -> None:
    fm = note.frontmatter
    db.execute("DELETE FROM notes WHERE path = ?", (note.path,))
    db.execute(
        """
        INSERT INTO notes (
            path, title, word_count, mtime, content_hash, frontmatter_json,
            origin, stage, type, created_at, updated_at, kind, has_canvas, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            note.path,
            note.title,
            note.word_count,
            mtime,
            note.content_hash,
            json.dumps(fm, default=str, ensure_ascii=False),
            _str_or_none(fm.get("origin")),
            _str_or_none(fm.get("stage")),
            _str_or_none(fm.get("type")),
            _str_or_none(fm.get("created")),
            _str_or_none(fm.get("updated")),
            "md",
            0,
            time.time(),
        ),
    )
    if note.headings:
        db.executemany(
            "INSERT INTO headings (path, level, text, line_no) VALUES (?, ?, ?, ?)",
            [(note.path, h.level, h.text, h.line_no) for h in note.headings],
        )
    if note.links:
        db.executemany(
            "INSERT INTO links (src_path, target_text, target_path, alias, line_no) "
            "VALUES (?, ?, NULL, ?, ?)",
            [(note.path, link.target_text, link.alias, link.line_no) for link in note.links],
        )
    if note.tags:
        db.executemany(
            "INSERT INTO tags (path, tag) VALUES (?, ?)",
            [(note.path, t) for t in note.tags],
        )
    if note.aliases:
        db.executemany(
            "INSERT INTO aliases (path, alias) VALUES (?, ?)",
            [(note.path, a) for a in note.aliases],
        )


def _str_or_none(v) -> str | None:
    return None if v is None else str(v)


def _resolve_links(db: sqlite3.Connection) -> tuple[int, int]:
    """Resolve link target_text → target_path. Strategy: literal path → basename → alias."""
    note_paths = [row[0] for row in db.execute("SELECT path FROM notes")]
    paths_set = set(note_paths)
    paths_lower = {p.lower(): p for p in note_paths}

    basename_map: dict[str, str] = {}
    for p in note_paths:
        basename_map.setdefault(PurePosixPath(p).stem.lower(), p)

    alias_map: dict[str, str] = {}
    for path, alias in db.execute("SELECT path, alias FROM aliases"):
        alias_map.setdefault(alias.lower(), path)

    resolved = 0
    broken = 0
    updates: list[tuple[str | None, int]] = []
    for rowid, target_text in db.execute("SELECT rowid, target_text FROM links").fetchall():
        target = _resolve_one(target_text, paths_set, paths_lower, basename_map, alias_map)
        updates.append((target, rowid))
        if target:
            resolved += 1
        else:
            broken += 1
    db.executemany("UPDATE links SET target_path = ? WHERE rowid = ?", updates)
    return resolved, broken


def _resolve_one(
    target_text: str,
    paths_set: set[str],
    paths_lower: dict[str, str],
    basename_map: dict[str, str],
    alias_map: dict[str, str],
) -> str | None:
    candidate = target_text if target_text.endswith(".md") else f"{target_text}.md"
    if candidate in paths_set:
        return candidate
    if candidate.lower() in paths_lower:
        return paths_lower[candidate.lower()]
    key = PurePosixPath(target_text).stem.lower()
    if key in basename_map:
        return basename_map[key]
    if target_text.lower() in alias_map:
        return alias_map[target_text.lower()]
    return None


def _write_state(vault: Path, stats: IndexStats) -> None:
    sp = state_path(vault)
    sp.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": SCHEMA_VERSION,
        "last_full_index_at": time.time(),
        "stats": asdict(stats),
    }
    sp.write_text(json.dumps(state, indent=2, default=str))
