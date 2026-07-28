"""Walk the vault, parse changed notes, write to sqlite. Idempotent and incremental on mtime."""

import json
import posixpath
import sqlite3
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from . import flip_conventions, okf_conventions
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
    flip_bundles: int = 0
    flip_handles: int = 0
    flip_id_collisions: int = 0
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

        bundles, handles, handle_map = _annotate_flip(db, vault)
        stats.flip_bundles = bundles
        stats.flip_handles = handles

        resolved, broken = _resolve_links(db, handle_map, stats)
        md_resolved, md_broken = _resolve_md_links(db)
        stats.links_resolved = resolved + md_resolved
        stats.links_broken = broken + md_broken

        _annotate_okf_sources(db)

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
    trust = okf_conventions.lift_trust_columns(fm)
    db.execute("DELETE FROM notes WHERE path = ?", (note.path,))
    db.execute(
        """
        INSERT INTO notes (
            path, title, word_count, mtime, content_hash, frontmatter_json,
            origin, stage, type, created_at, updated_at, kind, has_canvas, indexed_at,
            status, stale_after, generated_by, generated_at,
            verified_count, verified_human, verified_last_at, sources_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            trust["status"],
            trust["stale_after"],
            trust["generated_by"],
            trust["generated_at"],
            trust["verified_count"],
            trust["verified_human"],
            trust["verified_last_at"],
            trust["sources_count"],
        ),
    )
    if note.headings:
        db.executemany(
            "INSERT INTO headings (path, level, text, line_no) VALUES (?, ?, ?, ?)",
            [(note.path, h.level, h.text, h.line_no) for h in note.headings],
        )
    if note.links:
        db.executemany(
            "INSERT INTO links (src_path, target_text, target_path, target_anchor, alias, line_no) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            [
                (note.path, link.target_text, link.anchor, link.alias, link.line_no)
                for link in note.links
            ],
        )
    if note.md_links:
        db.executemany(
            "INSERT INTO links (src_path, target_text, target_path, target_anchor, alias, "
            "line_no, kind) VALUES (?, ?, NULL, ?, ?, ?, 'md')",
            [
                (note.path, link.target_text, link.anchor, link.alias, link.line_no)
                for link in note.md_links
            ],
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


def _annotate_flip(db: sqlite3.Connection, vault: Path) -> tuple[int, int, dict[str, str]]:
    """Detect flip bundle roots and annotate notes with bundle_path/bundle_handle/flip_id.

    Returns (bundle_count, handle_count, handle -> bundle_path map). Bundle roots
    come from the DB (frontmatter_json), not the filesystem, so unchanged notes
    are covered on incremental runs. bundle_path AND flip_id are recomputed for
    ALL notes each run (handles bundle-root creation/deletion without touching
    entity notes). flip_id is only meaningful INSIDE a bundle: an `id: Q4` in
    frontmatter outside any bundle stays NULL, so flip-free vaults carry no
    flip_id rows at all. No-op on flip-free vaults.
    """
    fms: dict[str, dict] = {}
    bundle_dirs: list[str] = []
    for path, fm_json in db.execute("SELECT path, frontmatter_json FROM notes").fetchall():
        try:
            fm = json.loads(fm_json) or {}
        except json.JSONDecodeError:
            fm = {}
        if not isinstance(fm, dict):
            fm = {}
        fms[path] = fm
        if (
            path == "index.md" or path.endswith("/index.md")
        ) and flip_conventions.is_bundle_root(fm):
            bundle_dirs.append(path[: -len("index.md")].rstrip("/"))  # "" = vault root

    if not bundle_dirs:
        db.execute(
            "UPDATE notes SET bundle_path = NULL, bundle_handle = NULL, flip_id = NULL "
            "WHERE bundle_path IS NOT NULL OR bundle_handle IS NOT NULL OR flip_id IS NOT NULL"
        )
        return 0, 0, {}

    # Longest-prefix (nearest ancestor) wins for nested bundles.
    bundle_dirs.sort(key=len, reverse=True)
    updates: list[tuple[str | None, str | None, str]] = []
    for path, fm in fms.items():
        bundle = _containing_bundle(path, bundle_dirs)
        flip_id = flip_conventions.extract_flip_id(fm) if bundle is not None else None
        updates.append((bundle, flip_id, path))
    db.executemany(
        "UPDATE notes SET bundle_path = ?, flip_id = ?, bundle_handle = NULL WHERE path = ?",
        updates,
    )

    # Workspace handle table — the one piece of I/O in flip awareness.
    handle_map: dict[str, str] = {}
    try:
        text = (vault / ".flip" / "workspace.toml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    if text:
        parsed = flip_conventions.parse_workspace_toml(text)
        bundle_set = set(bundle_dirs)
        handle_map = {h: p for h, p in parsed.items() if p in bundle_set}

    # Bind one handle per bundle path; lexicographically smallest wins.
    handle_by_bundle: dict[str, str] = {}
    for handle in sorted(handle_map):
        handle_by_bundle.setdefault(handle_map[handle], handle)
    if handle_by_bundle:
        db.executemany(
            "UPDATE notes SET bundle_handle = ? WHERE bundle_path = ?",
            [(h, bp) for bp, h in handle_by_bundle.items()],
        )
    return len(bundle_dirs), len(handle_map), handle_map


def _containing_bundle(path: str, bundle_dirs_longest_first: list[str]) -> str | None:
    for d in bundle_dirs_longest_first:
        if d == "" or path.startswith(d + "/"):
            return d
    return None


def _resolve_links(
    db: sqlite3.Connection, handle_map: dict[str, str], stats: IndexStats
) -> tuple[int, int]:
    """Resolve link target_text → target_path.

    Strategy: literal path → basename → bundle-scoped flip id → workspace-qualified
    flip id → alias. The two flip steps are no-ops on flip-free vaults (empty maps).
    """
    note_paths = [row[0] for row in db.execute("SELECT path FROM notes")]
    paths_set = set(note_paths)
    paths_lower = {p.lower(): p for p in note_paths}

    basename_map: dict[str, str] = {}
    for p in note_paths:
        basename_map.setdefault(PurePosixPath(p).stem.lower(), p)

    alias_map: dict[str, str] = {}
    for path, alias in db.execute("SELECT path, alias FROM aliases"):
        alias_map.setdefault(alias.lower(), path)

    bundle_by_src: dict[str, str] = dict(
        db.execute("SELECT path, bundle_path FROM notes WHERE bundle_path IS NOT NULL")
    )
    flip_id_map: dict[tuple[str, str], str] = {}
    for path, bundle_path, flip_id in db.execute(
        "SELECT path, bundle_path, flip_id FROM notes "
        "WHERE flip_id IS NOT NULL AND bundle_path IS NOT NULL ORDER BY path"
    ):
        key = (bundle_path, flip_id)
        if key in flip_id_map:  # same id twice in one bundle: first wins by path sort
            stats.flip_id_collisions += 1
            continue
        flip_id_map[key] = path

    resolved = 0
    broken = 0
    updates: list[tuple[str | None, int]] = []
    for rowid, src_path, target_text, anchor in db.execute(
        "SELECT rowid, src_path, target_text, target_anchor FROM links WHERE kind = 'wiki'"
    ).fetchall():
        target = _resolve_one(
            target_text,
            anchor,
            bundle_by_src.get(src_path),
            paths_set,
            paths_lower,
            basename_map,
            alias_map,
            flip_id_map,
            handle_map,
        )
        updates.append((target, rowid))
        if target:
            resolved += 1
        else:
            broken += 1
    db.executemany("UPDATE links SET target_path = ? WHERE rowid = ?", updates)
    return resolved, broken


def _resolve_one(
    target_text: str,
    anchor: str | None,
    src_bundle: str | None,
    paths_set: set[str],
    paths_lower: dict[str, str],
    basename_map: dict[str, str],
    alias_map: dict[str, str],
    flip_id_map: dict[tuple[str, str], str],
    handle_map: dict[str, str],
) -> str | None:
    candidate = target_text if target_text.endswith(".md") else f"{target_text}.md"
    if candidate in paths_set:
        return candidate
    if candidate.lower() in paths_lower:
        return paths_lower[candidate.lower()]
    key = PurePosixPath(target_text).stem.lower()
    if key in basename_map:
        return basename_map[key]
    # Bare flip id, bundle-scoped. Deliberately BEFORE the vault-wide alias map:
    # entity pages carry their bare id as an alias, and the alias map is
    # first-wins — two bundles both holding an A1 would otherwise cross-resolve.
    # TERMINAL for id-shaped targets inside a bundle: an id the bundle lacks is
    # unresolved, never a cross-bundle guess through the alias map. ("is not
    # None" keeps the vault-root-as-bundle case, src_bundle == "", truthy-safe.)
    if src_bundle is not None and flip_conventions.FLIP_ID_RE.match(target_text):
        return flip_id_map.get((src_bundle, target_text))
    # Qualified: [[handle:A3]] or the deprecated [[handle#A3]] (via the anchor).
    q = flip_conventions.split_qualified(target_text, anchor)
    if q is not None and q[0] in handle_map:
        hit = flip_id_map.get((handle_map[q[0]], q[1]))
        if hit:
            return hit
    if target_text.lower() in alias_map:
        return alias_map[target_text.lower()]
    return None


def _okf_roots(db: sqlite3.Connection) -> list[str]:
    """Directories whose index.md carries frontmatter — OKF bundle roots.

    OKF permits index.md frontmatter only on a bundle root (§12), so presence
    of any frontmatter marks the root. Flip bundle roots are a subset (their
    index.md carries okf_version + flip), but flip's own bundle_path wins for
    notes inside a flip bundle (see _md_root). Longest-first for nearest-
    ancestor matching via _containing_bundle.
    """
    roots = [
        path[: -len("index.md")].rstrip("/")
        for (path,) in db.execute(
            "SELECT path FROM notes WHERE (path = 'index.md' OR path LIKE '%/index.md') "
            "AND frontmatter_json != '{}'"
        )
    ]
    roots.sort(key=len, reverse=True)
    return roots


def _md_root(path: str, flip_bundle: str | None, okf_roots_longest_first: list[str]) -> str:
    """The root a `/…` (bundle-absolute) markdown link resolves against.

    The containing flip bundle when there is one; else the nearest ancestor
    with a frontmatter'd index.md; else the vault root ("")."""
    if flip_bundle is not None:
        return flip_bundle
    root = _containing_bundle(path, okf_roots_longest_first)
    return root if root is not None else ""


def _resolve_md_links(db: sqlite3.Connection) -> tuple[int, int]:
    """Resolve markdown-link target_text → target_path.

    Deterministic path arithmetic only — relative targets against the note's
    directory, `/…` targets against the bundle root — with the standard
    directory fallbacks (`dir/` → dir/index.md; extensionless → +.md, then
    /index.md). No basename, alias, or fuzzy fallback: an unresolved target
    stays NULL, recorded but never guessed at (broken links are legal OKF).
    """
    paths_set = {row[0] for row in db.execute("SELECT path FROM notes")}
    okf_roots = _okf_roots(db)
    bundle_by_src: dict[str, str] = dict(
        db.execute("SELECT path, bundle_path FROM notes WHERE bundle_path IS NOT NULL")
    )
    resolved = 0
    broken = 0
    updates: list[tuple[str | None, int]] = []
    for rowid, src_path, target_text in db.execute(
        "SELECT rowid, src_path, target_text FROM links WHERE kind = 'md'"
    ).fetchall():
        root = _md_root(src_path, bundle_by_src.get(src_path), okf_roots)
        target = _resolve_md_target(target_text, src_path, root, paths_set)
        updates.append((target, rowid))
        if target:
            resolved += 1
        else:
            broken += 1
    db.executemany("UPDATE links SET target_path = ? WHERE rowid = ?", updates)
    return resolved, broken


def _resolve_md_target(
    target_text: str, src_path: str, root: str, paths_set: set[str]
) -> str | None:
    decoded = urllib.parse.unquote(target_text)
    if decoded.startswith("/"):
        joined = f"{root}/{decoded[1:]}" if root else decoded[1:]
    else:
        joined = posixpath.join(posixpath.dirname(src_path), decoded)
    cand = posixpath.normpath(joined)
    if cand in ("", ".", "..") or cand.startswith("../"):
        return None  # escapes the vault, or names nothing
    if cand in paths_set:
        return cand
    if decoded.endswith("/"):
        idx = f"{cand}/index.md"
        return idx if idx in paths_set else None
    if "." not in posixpath.basename(cand):
        for c in (f"{cand}.md", f"{cand}/index.md"):
            if c in paths_set:
                return c
    return None


def _annotate_okf_sources(db: sqlite3.Connection) -> None:
    """Count unresolved provenance entries per note carrying `sources`.

    Conservative by design: an entry is unresolved when it has no resource at
    all (a dangling cite keeps just its id) or when its resource is a
    bundle-path-shaped .md that doesn't land on an indexed note. External URLs,
    scope descriptors, and non-md bundle assets are never counted — eno can't
    check them, so it doesn't claim to.
    """
    paths_set = {row[0] for row in db.execute("SELECT path FROM notes")}
    okf_roots = _okf_roots(db)
    bundle_by_src: dict[str, str] = dict(
        db.execute("SELECT path, bundle_path FROM notes WHERE bundle_path IS NOT NULL")
    )
    updates: list[tuple[int, str]] = []
    for path, fm_json in db.execute(
        "SELECT path, frontmatter_json FROM notes WHERE sources_count IS NOT NULL"
    ).fetchall():
        try:
            fm = json.loads(fm_json) or {}
        except json.JSONDecodeError:
            fm = {}
        if not isinstance(fm, dict):
            fm = {}
        root = _md_root(path, bundle_by_src.get(path), okf_roots)
        unresolved = 0
        for entry in okf_conventions.parse_sources(fm):
            resource = entry.get("resource")
            shape = okf_conventions.classify_resource(resource)
            if shape == "missing" or (
                shape == "note-path"
                and _resolve_md_target(
                    str(resource).strip().split("#", 1)[0], path, root, paths_set
                )
                is None
            ):
                unresolved += 1
        updates.append((unresolved, path))
    if updates:
        db.executemany(
            "UPDATE notes SET sources_unresolved = ? WHERE path = ?", updates
        )


def _write_state(vault: Path, stats: IndexStats) -> None:
    sp = state_path(vault)
    sp.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": SCHEMA_VERSION,
        "last_full_index_at": time.time(),
        "stats": asdict(stats),
    }
    sp.write_text(json.dumps(state, indent=2, default=str))
