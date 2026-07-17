"""Read-only queries over the vault index. Pure functions over a sqlite Connection.

These are the primitives behind every read endpoint — the service handlers and the
LocalBackend both call into here. No I/O, no http, no excerpt building (that's a vault
file read, lives in eno.excerpt). Excerpts are layered on top by callers.
"""

import json
import math
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta

from .views import (
    BrokenLink,
    FrontierNote,
    HeadingView,
    Hit,
    HotCache,
    HygieneIssue,
    HygieneReport,
    Neighborhood,
    NoteRef,
    NoteView,
)


def search(
    db: sqlite3.Connection, q: str, *, kind: str = "title", limit: int = 20
) -> list[Hit]:
    q_lower = q.lower()
    if kind == "title":
        rows = db.execute(
            """
            SELECT path, title FROM notes
            WHERE LOWER(title) LIKE ?
            ORDER BY LENGTH(title), title
            LIMIT ?
            """,
            (f"%{q_lower}%", limit),
        ).fetchall()
        return [Hit(path=p, title=t, score=1.0, matched_in="title") for p, t in rows]
    if kind == "tag":
        rows = db.execute(
            """
            SELECT DISTINCT n.path, n.title FROM notes n
            JOIN tags t ON t.path = n.path
            WHERE LOWER(t.tag) = ?
            ORDER BY n.title
            LIMIT ?
            """,
            (q_lower, limit),
        ).fetchall()
        return [Hit(path=p, title=t, score=1.0, matched_in="tag") for p, t in rows]
    raise ValueError(f"unknown search kind: {kind}")


def note(db: sqlite3.Connection, path: str) -> NoteView | None:
    row = db.execute(
        "SELECT path, title, word_count, frontmatter_json, flip_id, bundle_path, bundle_handle "
        "FROM notes WHERE path = ?",
        (path,),
    ).fetchone()
    if not row:
        return None
    try:
        fm = json.loads(row[3]) or {}
    except json.JSONDecodeError:
        fm = {}
    headings = [
        HeadingView(level=lvl, text=text, line_no=ln)
        for lvl, text, ln in db.execute(
            "SELECT level, text, line_no FROM headings WHERE path = ? ORDER BY line_no",
            (path,),
        )
    ]
    return NoteView(
        path=row[0],
        title=row[1],
        word_count=row[2],
        frontmatter=fm,
        headings=headings,
        flip_id=row[4],
        bundle_path=row[5],
        bundle_handle=row[6],
    )


def neighbors(db: sqlite3.Connection, path: str) -> Neighborhood | None:
    row = db.execute("SELECT title FROM notes WHERE path = ?", (path,)).fetchone()
    if not row:
        return None
    backlinks = [
        NoteRef(path=p, title=t, word_count=wc)
        for p, t, wc in db.execute(
            """
            SELECT DISTINCT n.path, n.title, n.word_count
            FROM links l JOIN notes n ON n.path = l.src_path
            WHERE l.target_path = ?
            ORDER BY n.title
            """,
            (path,),
        )
    ]
    outbound = [
        NoteRef(path=p, title=t, word_count=wc)
        for p, t, wc in db.execute(
            """
            SELECT DISTINCT n.path, n.title, n.word_count
            FROM links l JOIN notes n ON n.path = l.target_path
            WHERE l.src_path = ? AND l.target_path IS NOT NULL
            ORDER BY n.title
            """,
            (path,),
        )
    ]
    return Neighborhood(path=path, title=row[0], backlinks=backlinks, outbound=outbound)


def orphans(
    db: sqlite3.Connection,
    *,
    folder: str | None = None,
    min_words: int = 0,
    limit: int = 100,
) -> list[NoteRef]:
    sql = """
        SELECT path, title, word_count FROM notes
        WHERE path NOT IN (
            SELECT target_path FROM links WHERE target_path IS NOT NULL
        )
          AND word_count >= ?
    """
    params: list = [min_words]
    if folder:
        sql += " AND path LIKE ?"
        params.append(f"{folder.rstrip('/')}/%")
    sql += " ORDER BY word_count DESC LIMIT ?"
    params.append(limit)
    return [NoteRef(path=p, title=t, word_count=wc) for p, t, wc in db.execute(sql, params)]


def stubs(
    db: sqlite3.Connection, *, max_words: int = 80, limit: int = 100
) -> list[NoteRef]:
    rows = db.execute(
        """
        SELECT path, title, word_count FROM notes
        WHERE word_count <= ?
          AND path NOT IN (SELECT DISTINCT src_path FROM links)
        ORDER BY word_count, path
        LIMIT ?
        """,
        (max_words, limit),
    )
    return [NoteRef(path=p, title=t, word_count=wc) for p, t, wc in rows]


def stale(
    db: sqlite3.Connection,
    *,
    older_than_days: int = 180,
    stages: list[str] | None = None,
    limit: int = 100,
) -> list[NoteRef]:
    """Notes past a recency threshold.

    Prefers frontmatter `updated:` when present (since mtime resets on
    git clone — the indexer's `notes.updated_at` column carries the YAML
    value). Falls back to mtime when `updated_at` is empty.

    String comparison on `updated_at` works because we expect ISO 8601
    dates (YYYY-MM-DD); both pyyaml's date rendering and the convention
    in CHARTER produce that format.
    """
    cutoff_mtime = time.time() - older_than_days * 86400
    cutoff_iso = (
        datetime.now(UTC) - timedelta(days=older_than_days)
    ).strftime("%Y-%m-%d")

    sql = """
        SELECT path, title, word_count FROM notes
        WHERE (
            (updated_at IS NOT NULL AND updated_at != '' AND substr(updated_at, 1, 10) < ?)
            OR
            ((updated_at IS NULL OR updated_at = '') AND mtime < ?)
        )
    """
    params: list = [cutoff_iso, cutoff_mtime]
    if stages:
        placeholders = ",".join("?" * len(stages))
        sql += f" AND stage IN ({placeholders})"
        params.extend(stages)
    else:
        # Default: never stale-flag reference or archived notes (per SKETCH).
        sql += " AND (stage IS NULL OR stage NOT IN ('reference', 'archived'))"
    sql += " ORDER BY mtime LIMIT ?"
    params.append(limit)
    return [NoteRef(path=p, title=t, word_count=wc) for p, t, wc in db.execute(sql, params)]


def _age_days(updated_at: str | None, mtime: float | None) -> float:
    """Days since a note was last touched. Mirrors stale() preference order:
    frontmatter `updated:` (ISO date) wins; fall back to mtime; default large."""
    if updated_at:
        try:
            d = date.fromisoformat(updated_at[:10])
            return max(0.0, float((date.today() - d).days))
        except ValueError:
            pass
    if mtime:
        return max(0.0, (time.time() - mtime) / 86400.0)
    return 10_000.0


def frontier(
    db: sqlite3.Connection,
    *,
    folder: str | None = None,
    halflife_days: float = 30.0,
    limit: int = 20,
    include_nonpositive: bool = False,
    exclude_types: list[str] | None = None,
) -> list[FrontierNote]:
    """Pages where the user is actively reaching outward.

    score = (out_degree - in_degree) * exp(-age_days / halflife_days)

    High score = points at many things, is pointed at by few, recently touched.
    Hub pages and stale pages drop. Borrowed from claude-obsidian's
    DragonScale Mechanism 4 (boundary-first autoresearch); the math is
    unchanged, but degree counting runs in SQL over eno's existing index
    rather than re-parsing wikilinks.
    """
    sql = """
        SELECT
            n.path, n.title, n.word_count, n.updated_at, n.mtime,
            COALESCE(out_d.cnt, 0) AS out_degree,
            COALESCE(in_d.cnt, 0) AS in_degree
        FROM notes n
        LEFT JOIN (
            SELECT src_path, COUNT(DISTINCT target_path) AS cnt
            FROM links
            WHERE target_path IS NOT NULL
            GROUP BY src_path
        ) out_d ON out_d.src_path = n.path
        LEFT JOIN (
            SELECT target_path, COUNT(DISTINCT src_path) AS cnt
            FROM links
            WHERE target_path IS NOT NULL
            GROUP BY target_path
        ) in_d ON in_d.target_path = n.path
        WHERE 1=1
    """
    params: list = []
    if folder:
        sql += " AND n.path LIKE ?"
        params.append(f"{folder.rstrip('/')}/%")
    if exclude_types:
        placeholders = ",".join("?" * len(exclude_types))
        sql += f" AND (n.type IS NULL OR n.type NOT IN ({placeholders}))"
        params.extend(exclude_types)

    rows = db.execute(sql, params).fetchall()
    scored: list[FrontierNote] = []
    for path, title, wc, updated_at, mtime, out_deg, in_deg in rows:
        age = _age_days(updated_at, mtime)
        rw = math.exp(-age / halflife_days) if halflife_days > 0 else 0.0
        score = (out_deg - in_deg) * rw
        if not include_nonpositive and score <= 0.0:
            continue
        scored.append(
            FrontierNote(
                path=path,
                title=title,
                word_count=wc,
                out_degree=out_deg,
                in_degree=in_deg,
                age_days=round(age, 2),
                recency_weight=round(rw, 4),
                score=round(score, 4),
            )
        )
    scored.sort(key=lambda f: (-f.score, f.path))
    return scored[:limit]


def recent_appends(
    db: sqlite3.Connection,
    *,
    within_days: int = 7,
    limit: int = 8,
) -> list[NoteRef]:
    """Notes touched within the recency window. mtime-based — captures both
    fresh creation and append-style edits."""
    cutoff = time.time() - within_days * 86400
    rows = db.execute(
        """
        SELECT path, title, word_count FROM notes
        WHERE mtime >= ?
        ORDER BY mtime DESC
        LIMIT ?
        """,
        (cutoff, limit),
    )
    return [NoteRef(path=p, title=t, word_count=wc) for p, t, wc in rows]


def agent_recent(
    db: sqlite3.Connection,
    *,
    agent_name: str,
    within_days: int = 14,
    limit: int = 5,
) -> list[NoteRef]:
    """Notes whose frontmatter author matches the given agent, modified within
    the window. Used to remind the agent of its own recent contributions on
    session start."""
    if not agent_name:
        return []
    cutoff = time.time() - within_days * 86400
    target = f"[[{agent_name}]]"
    rows = db.execute(
        """
        SELECT path, title, word_count FROM notes
        WHERE mtime >= ?
          AND json_extract(frontmatter_json, '$.author') = ?
        ORDER BY mtime DESC
        LIMIT ?
        """,
        (cutoff, target, limit),
    )
    return [NoteRef(path=p, title=t, word_count=wc) for p, t, wc in rows]


def hot(
    db: sqlite3.Connection,
    *,
    agent_name: str = "",
    frontier_limit: int = 5,
    recent_appends_limit: int = 8,
    recent_appends_within_days: int = 7,
    concepts_limit: int = 5,
    agent_recent_limit: int = 5,
    agent_recent_within_days: int = 14,
) -> HotCache:
    """Aggregate a session-start "what's hot" bundle from the index.

    Pure derive: no file written, always fresh. Compose:
      - frontier — high outward-reach pages (live work threads)
      - recent_appends — notes touched in the recency window
      - top_concepts — incipient wikilinks by mention_count (groundwork)
      - agent_recent — notes the agent itself authored recently (its
        contribution trail in the vault)
    """
    from . import garden  # local import: garden imports queries

    fr = frontier(db, limit=frontier_limit)
    ra = recent_appends(
        db,
        within_days=recent_appends_within_days,
        limit=recent_appends_limit,
    )
    _drift, concepts = garden.classify_broken_links(db)
    top_concepts = concepts[:concepts_limit]
    ar = agent_recent(
        db,
        agent_name=agent_name,
        within_days=agent_recent_within_days,
        limit=agent_recent_limit,
    )
    return HotCache(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        frontier=fr,
        recent_appends=ra,
        top_concepts=top_concepts,
        agent_recent=ar,
        agent_name=agent_name,
    )


def broken_links(
    db: sqlite3.Connection, *, limit: int = 200
) -> list[BrokenLink]:
    rows = db.execute(
        """
        SELECT src_path, target_text, line_no FROM links
        WHERE target_path IS NULL
        ORDER BY src_path, line_no
        LIMIT ?
        """,
        (limit,),
    )
    return [BrokenLink(src_path=s, target_text=t, line_no=ln) for s, t, ln in rows]


# Frontmatter fields that we expect every fully-classified note to carry.
# `title` is derived from H1 and not strictly required in frontmatter (per AGENTS.md
# convention that filename === H1), so we audit only origin and stage here.
HYGIENE_REQUIRED = ("origin", "stage")


def hygiene(db: sqlite3.Connection) -> HygieneReport:
    issues: list[HygieneIssue] = []
    counts: dict[str, int] = {f: 0 for f in HYGIENE_REQUIRED}
    counts["total"] = 0
    for path, fm_json in db.execute("SELECT path, frontmatter_json FROM notes"):
        counts["total"] += 1
        try:
            fm = json.loads(fm_json) or {}
        except json.JSONDecodeError:
            fm = {}
        missing = [f for f in HYGIENE_REQUIRED if not fm.get(f)]
        if missing:
            for f in missing:
                counts[f] += 1
            issues.append(HygieneIssue(path=path, missing=missing))
    return HygieneReport(issues=issues, counts=counts)
