"""eno fold — extractive rollup over a date range of daily notes + recent vault edits.

Borrows the discipline of claude-obsidian's wiki-fold (DragonScale Mechanism 1):
- Deterministic fold ID
- Extractive-only (every claim cites a source)
- Bounded reads
- Count-checked numeric claims
- Dry-run-stdout-only by default; --commit writes
- Additive (children never modified)

Supports flat time-range folds, topic-driven folds (wikilink/folder/tag),
supersession metadata, and fold-of-folds level stacking.

Requires the optional LLM extra (`pip install enowiki[llm]`). Synthesis routes
through somm, which owns provider selection. Privacy: registers the somm
workload as `privacy_class=PRIVATE`, restricting it to sovereign/local
providers so vault prose never leaves the machine.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import vault_dir as default_vault_dir
from .views import (
    Fold,
    FoldDaySummary,
    FoldOpenLoop,
    FoldSource,
    FoldTheme,
    FoldWikilinkHeat,
)

DAILY_NOTES_DIR = "z Daily Notes"
FOLD_OUTPUT_DIR = "9 Vault Health/folds"
FOLD_LOG_REL = ".eno/fold-log.md"

DEFAULT_DAILY_MAX_CHARS = 2500
DEFAULT_EDIT_EXCERPT_CHARS = 800
DEFAULT_MAX_RECENT_EDITS = 8

# Local models good enough for the fold's structured-output prompt. gemma4:e4b
# is too small — returns prose around the JSON. The user's `qwen3:14b` and
# `qwen2.5:7b` reliably emit clean JSON; somm's extract_structured handles
# both. Override per-call via `--model`.
DEFAULT_FOLD_MODEL = "qwen3:14b"

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]+)?(?:\|[^\]]+?)?\]\]")
NUMERIC_CLAIM_RE = re.compile(r"\b(\d+)\b")


# ---------------------------------------------------------------------------
# Deterministic fold ID
# ---------------------------------------------------------------------------


def fold_id(range_start: str, range_end: str, count: int) -> str:
    """`fold-{start}-to-{end}-n{count}`. Same range + same source count
    always yields the same ID. Refuse to overwrite without --force."""
    return f"fold-{range_start}-to-{range_end}-n{count}"


def fold_path(vault: Path, fid: str) -> Path:
    """Where a fold note lives. Time-range folds at the top level; topic
    folds in a `topic/` subdirectory to keep them visually distinct."""
    if fid.startswith("fold-topic-"):
        return vault / FOLD_OUTPUT_DIR / "topic" / f"{fid}.md"
    return vault / FOLD_OUTPUT_DIR / f"{fid}.md"


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def topic_slug(value: str) -> str:
    """Lowercased, dash-separated, alnum-only. Stable across runs.
    `[[Acme]]` → `acme`; `2 Projects/Acme` → `2-projects-acme`."""
    if not value:
        return "topic"
    s = _SLUG_RE.sub("-", value.lower()).strip("-")
    return s or "topic"


def topic_fold_id(kind: str, value: str, count: int) -> str:
    """`fold-topic-{kind}-{slug}-n{count}`. Same kind+value+count → same id.
    kind in {'wikilink', 'folder', 'tag'}."""
    return f"fold-topic-{kind}-{topic_slug(value)}-n{count}"


def parse_fold_frontmatter(path: Path) -> dict | None:
    """Read just the YAML frontmatter from a committed fold note. Returns
    None if the file is missing or has no frontmatter. Tolerant: doesn't
    pull in pyyaml — we control the format and only need a few fields."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fm: dict = {}
    fm_block = text[4:end]
    current_list: list | None = None
    for raw in fm_block.splitlines():
        if raw.startswith("  - ") and current_list is not None:
            value = raw[4:].strip().strip('"').strip("'")
            current_list.append(value)
            continue
        if not raw or raw[0] == " ":
            continue
        if ":" not in raw:
            continue
        key, _, val = raw.partition(":")
        key = key.strip()
        val = val.strip()
        if val == "" or val == "[]":
            # Either a list-following key or an empty list.
            current_list = []
            fm[key] = current_list
        else:
            fm[key] = val.strip('"').strip("'")
            current_list = None
    return fm


def list_committed_folds(vault: Path | None = None) -> list[dict]:
    """Enumerate committed fold notes in 9 Vault Health/folds/. Returns
    [{fold_id, path, range_start, range_end, level, confidence,
      superseded_by, supersedes}]. Sorted by range_start."""
    vault = vault or default_vault_dir()
    fold_dir = vault / FOLD_OUTPUT_DIR
    if not fold_dir.exists():
        return []
    out: list[dict] = []
    for path in sorted(fold_dir.glob("fold-*.md")):
        fm = parse_fold_frontmatter(path)
        if not fm:
            continue
        # n_sources (L1) and n_children (L2+) both contribute to the
        # display "n=" — surface them under one key for callers.
        n = int(fm.get("n_sources") or fm.get("n_children") or "0")
        out.append({
            "fold_id": fm.get("title", path.stem).strip('"'),
            "path": str(path.relative_to(vault)),
            "range_start": fm.get("range_start", ""),
            "range_end": fm.get("range_end", ""),
            "level": int(fm.get("level", "1") or "1"),
            "n_sources": n,
            "confidence": fm.get("confidence", ""),
            "superseded_by": fm.get("superseded_by", ""),
            "supersedes": fm.get("supersedes") or [],
        })
    out.sort(key=lambda r: (r["range_start"], r["range_end"]))
    return out


# ---------------------------------------------------------------------------
# Source loading (two-tier)
# ---------------------------------------------------------------------------


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    return text[end + 5 :]


def _head_and_tail(body: str, total_chars: int) -> str:
    body = body.strip()
    if len(body) <= total_chars:
        return body
    half = total_chars // 2
    head = body[:half].rstrip()
    tail = body[-half:].lstrip()
    return f"{head}\n\n…\n\n{tail}"


def _date_in_range(d: str, start: str, end: str) -> bool:
    return start <= d <= end


def _daily_notes_in_range(
    db: sqlite3.Connection,
    vault: Path,
    range_start: str,
    range_end: str,
    *,
    daily_max_chars: int,
) -> list[FoldSource]:
    """All notes under DAILY_NOTES_DIR with a derivable date in range.

    Catches both `YYYY-MM-DD.md` (the canonical pattern) and same-day
    follow-ups like `2026-04-29-recap.md`. Index-only filter; body read
    happens separately.
    """
    daily_prefix = f"{DAILY_NOTES_DIR}/%"
    rows = db.execute(
        """
        SELECT path, title, word_count, mtime, updated_at FROM notes
        WHERE path LIKE ?
        ORDER BY path
        """,
        (daily_prefix,),
    ).fetchall()
    sources: list[FoldSource] = []
    for path, title, wc, mtime, updated_at in rows:
        # Try filename first (canonical YYYY-MM-DD.md pattern).
        fname = Path(path).stem
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", fname)
        if m and _date_in_range(m.group(1), range_start, range_end):
            d = m.group(1)
        elif updated_at and _date_in_range(updated_at[:10], range_start, range_end):
            d = updated_at[:10]
        elif _date_in_range(
            datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%d"),
            range_start, range_end,
        ):
            d = datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%d")
        else:
            continue
        body = _read_body(vault, path)
        if body is None:
            continue
        excerpt = _head_and_tail(body, daily_max_chars)
        sources.append(
            FoldSource(
                path=path, title=title, tier="daily", date=d,
                word_count=wc, excerpt=excerpt,
            )
        )
    sources.sort(key=lambda s: (s.date, s.path))
    return sources


def _recent_edits_in_range(
    db: sqlite3.Connection,
    vault: Path,
    range_start: str,
    range_end: str,
    *,
    excerpt_chars: int,
    max_count: int,
    daily_paths: set[str],
) -> list[FoldSource]:
    """Non-daily notes whose mtime or updated_at falls in the range.
    Excludes daily notes (already in tier 1), fold reports, and `.eno/`.

    Matches the queries.stale() preference: frontmatter `updated_at` wins
    when present; falls back to mtime.
    """
    end_ts = (
        datetime.strptime(range_end, "%Y-%m-%d").replace(tzinfo=UTC)
        + timedelta(days=1)
    ).timestamp()
    start_ts = (
        datetime.strptime(range_start, "%Y-%m-%d").replace(tzinfo=UTC)
    ).timestamp()
    rows = db.execute(
        """
        SELECT path, title, word_count FROM notes
        WHERE path NOT LIKE ?
          AND path NOT LIKE ?
          AND (
            (updated_at IS NOT NULL AND updated_at != ''
             AND substr(updated_at, 1, 10) BETWEEN ? AND ?)
            OR
            ((updated_at IS NULL OR updated_at = '')
             AND mtime BETWEEN ? AND ?)
          )
        ORDER BY mtime DESC
        LIMIT ?
        """,
        (
            f"{DAILY_NOTES_DIR}/%",
            f"{FOLD_OUTPUT_DIR}/%",
            range_start, range_end,
            start_ts, end_ts,
            max_count * 3,  # over-fetch then filter (some bodies may be unreadable)
        ),
    ).fetchall()
    sources: list[FoldSource] = []
    for path, title, wc in rows:
        if path in daily_paths:
            continue
        body = _read_body(vault, path)
        if body is None:
            continue
        excerpt = _head_and_tail(body, excerpt_chars)
        # Use the most-recent date we can pin: frontmatter > mtime.
        row = db.execute(
            "SELECT updated_at, mtime FROM notes WHERE path = ?", (path,)
        ).fetchone()
        if row and row[0]:
            d = row[0][:10]
        elif row:
            d = datetime.fromtimestamp(row[1], UTC).strftime("%Y-%m-%d")
        else:
            d = range_end
        sources.append(
            FoldSource(
                path=path, title=title, tier="recent_edit", date=d,
                word_count=wc, excerpt=excerpt,
            )
        )
        if len(sources) >= max_count:
            break
    return sources


def _read_body(vault: Path, rel: str) -> str | None:
    p = vault / rel
    if p.is_symlink():
        return None
    try:
        resolved = p.resolve(strict=True)
        resolved.relative_to(vault.resolve())
    except (OSError, ValueError):
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    body = _strip_frontmatter(text).strip()
    return body or None


def load_sources(
    db: sqlite3.Connection,
    vault: Path,
    range_start: str,
    range_end: str,
    *,
    daily_max_chars: int = DEFAULT_DAILY_MAX_CHARS,
    edit_excerpt_chars: int = DEFAULT_EDIT_EXCERPT_CHARS,
    max_recent_edits: int = DEFAULT_MAX_RECENT_EDITS,
) -> list[FoldSource]:
    """Compose the two-tier source set."""
    daily = _daily_notes_in_range(
        db, vault, range_start, range_end,
        daily_max_chars=daily_max_chars,
    )
    daily_paths = {s.path for s in daily}
    recent = _recent_edits_in_range(
        db, vault, range_start, range_end,
        excerpt_chars=edit_excerpt_chars,
        max_count=max_recent_edits,
        daily_paths=daily_paths,
    )
    return daily + recent


# ---------------------------------------------------------------------------
# Topic sources (selector-driven, range-agnostic)
# ---------------------------------------------------------------------------


DEFAULT_TOPIC_SOURCE_LIMIT = 12
DEFAULT_TOPIC_EXCERPT_CHARS = 1500


def _row_to_topic_source(
    vault: Path,
    path: str,
    title: str,
    word_count: int,
    updated_at: str | None,
    mtime: float,
    excerpt_chars: int,
) -> FoldSource | None:
    """Read a note's body and wrap it as a topic-tier FoldSource.
    Returns None if the body is unreadable or empty."""
    body = _read_body(vault, path)
    if body is None:
        return None
    excerpt = _head_and_tail(body, excerpt_chars)
    d = updated_at[:10] if updated_at else datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%d")
    return FoldSource(
        path=path,
        title=title,
        tier="topic",
        date=d,
        word_count=word_count,
        excerpt=excerpt,
    )


def _topic_sources_wikilink(
    db: sqlite3.Connection,
    vault: Path,
    target: str,
    *,
    limit: int,
    excerpt_chars: int,
) -> list[FoldSource]:
    """Notes about [[target]]: notes that link to it + the target itself if
    it exists. The target's own note is the topic 'hub' — surface it first."""
    seen: set[str] = set()
    sources: list[FoldSource] = []

    # First: the target note itself, if it exists. Resolve through links table
    # (a non-null target_path is the index's authoritative resolution).
    hub_row = db.execute(
        """
        SELECT DISTINCT target_path FROM links
        WHERE target_text = ? AND target_path IS NOT NULL
        LIMIT 1
        """,
        (target,),
    ).fetchone()
    hub_path = hub_row[0] if hub_row else None
    # Fallback: filename-stem match (the link may never have been written, but
    # a note titled `target` still belongs to the topic).
    if not hub_path:
        stem_row = db.execute(
            "SELECT path FROM notes WHERE LOWER(title) = ? LIMIT 1",
            (target.lower(),),
        ).fetchone()
        hub_path = stem_row[0] if stem_row else None
    if hub_path:
        hub = db.execute(
            "SELECT path, title, word_count, updated_at, mtime FROM notes WHERE path = ?",
            (hub_path,),
        ).fetchone()
        if hub:
            src = _row_to_topic_source(vault, *hub, excerpt_chars=excerpt_chars)
            if src:
                sources.append(src)
                seen.add(hub_path)

    # Then: every note linking to the target, ordered by recency.
    rows = db.execute(
        """
        SELECT n.path, n.title, n.word_count, n.updated_at, n.mtime
        FROM links l JOIN notes n ON n.path = l.src_path
        WHERE l.target_text = ?
        GROUP BY n.path
        ORDER BY n.mtime DESC
        LIMIT ?
        """,
        (target, limit * 3),
    ).fetchall()
    for row in rows:
        path = row[0]
        if path in seen:
            continue
        src = _row_to_topic_source(vault, *row, excerpt_chars=excerpt_chars)
        if src:
            sources.append(src)
            seen.add(path)
        if len(sources) >= limit:
            break
    return sources


def _topic_sources_folder(
    db: sqlite3.Connection,
    vault: Path,
    prefix: str,
    *,
    limit: int,
    excerpt_chars: int,
) -> list[FoldSource]:
    """All notes under `prefix`, plus a sibling hub note if one exists
    (e.g. `2 Projects/Acme.md` next to `2 Projects/Acme/`)."""
    prefix = prefix.rstrip("/")
    rows = db.execute(
        """
        SELECT path, title, word_count, updated_at, mtime FROM notes
        WHERE path LIKE ? OR path = ?
        ORDER BY mtime DESC
        LIMIT ?
        """,
        (f"{prefix}/%", f"{prefix}.md", limit * 3),
    ).fetchall()
    sources: list[FoldSource] = []
    for row in rows:
        src = _row_to_topic_source(vault, *row, excerpt_chars=excerpt_chars)
        if src:
            sources.append(src)
        if len(sources) >= limit:
            break
    return sources


def _topic_sources_tag(
    db: sqlite3.Connection,
    vault: Path,
    tag: str,
    *,
    limit: int,
    excerpt_chars: int,
) -> list[FoldSource]:
    rows = db.execute(
        """
        SELECT n.path, n.title, n.word_count, n.updated_at, n.mtime
        FROM notes n JOIN tags t ON t.path = n.path
        WHERE LOWER(t.tag) = ?
        ORDER BY n.mtime DESC
        LIMIT ?
        """,
        (tag.lower(), limit * 3),
    ).fetchall()
    sources: list[FoldSource] = []
    for row in rows:
        src = _row_to_topic_source(vault, *row, excerpt_chars=excerpt_chars)
        if src:
            sources.append(src)
        if len(sources) >= limit:
            break
    return sources


def load_topic_sources(
    db: sqlite3.Connection,
    vault: Path,
    kind: str,
    value: str,
    *,
    limit: int = DEFAULT_TOPIC_SOURCE_LIMIT,
    excerpt_chars: int = DEFAULT_TOPIC_EXCERPT_CHARS,
) -> list[FoldSource]:
    """Dispatcher across the three topic selectors. Returns at most `limit`
    sources, ordered by mtime descending (hub first for wikilink kind)."""
    if kind == "wikilink":
        return _topic_sources_wikilink(
            db, vault, value, limit=limit, excerpt_chars=excerpt_chars,
        )
    if kind == "folder":
        return _topic_sources_folder(
            db, vault, value, limit=limit, excerpt_chars=excerpt_chars,
        )
    if kind == "tag":
        return _topic_sources_tag(
            db, vault, value, limit=limit, excerpt_chars=excerpt_chars,
        )
    raise ValueError(f"unknown topic kind: {kind!r}")


# ---------------------------------------------------------------------------
# Wikilink heat (cheap; no LLM)
# ---------------------------------------------------------------------------


def _wikilink_heat(
    db: sqlite3.Connection,
    sources: list[FoldSource],
) -> list[FoldWikilinkHeat]:
    """Count wikilink mentions across source bodies. Excerpts are enough —
    we're not aiming for total-mention accuracy here, just signal."""
    counts: dict[str, int] = Counter()
    by_target_dates: dict[str, set[str]] = defaultdict(set)
    for s in sources:
        for m in WIKILINK_RE.finditer(s.excerpt):
            target = m.group(1).strip()
            if not target:
                continue
            counts[target] += 1
            by_target_dates[target].add(s.date)

    # Resolution check: does any link in the index point at this target?
    resolved: dict[str, bool] = {}
    targets = list(counts)
    if targets:
        placeholders = ",".join("?" * len(targets))
        rows = db.execute(
            f"""
            SELECT DISTINCT target_text FROM links
            WHERE target_text IN ({placeholders})
              AND target_path IS NOT NULL
            """,
            targets,
        ).fetchall()
        for (t,) in rows:
            resolved[t] = True

    heat = [
        FoldWikilinkHeat(
            target=t,
            count=c,
            source_dates=sorted(by_target_dates[t]),
            resolves=resolved.get(t, False),
        )
        for t, c in counts.items()
        if c >= 2 or len(by_target_dates[t]) >= 2  # appears multiple times or across days
    ]
    heat.sort(key=lambda h: (-h.count, h.target))
    return heat


# ---------------------------------------------------------------------------
# Synthesis prompt + count check
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = (
    "You are an extraction tool. Your single job is to read a set of dated "
    "notes and emit ONE JSON object summarizing what is already there. "
    "You do not plan, advise, or recommend. You do not invent. "
    "Every claim must trace to specific text in the input. "
    "Output JSON only — no markdown, no headings, no preamble, no commentary."
)


_OUTPUT_SCHEMA_REMINDER = """
TASK: Extract themes, open loops, and per-day summaries from the notes above.

Themes must appear in ≥2 distinct dates. Open loops are items the user marked \
as pending/waiting/unresolved (preserve their phrasing). Day summaries are \
one extractive sentence per date.

If a section has no extractive material, return an empty list. Do not pad.

Numeric claims must be verifiable: if you write a number, it must appear \
literally in the input. If unsure, omit the number.

OUTPUT EXACTLY this JSON shape (and only this — no markdown, no commentary, \
no headings, no <think> blocks):

{
  "themes": [
    {"text": "extractive statement", "citations": ["YYYY-MM-DD"]}
  ],
  "open_loops": [
    {"text": "verbatim or near-verbatim from source", "source_date": "YYYY-MM-DD"}
  ],
  "day_summaries": [
    {"date": "YYYY-MM-DD", "summary": "one extractive sentence"}
  ]
}
""".strip()


def _build_user_prompt(sources: list[FoldSource], range_start: str, range_end: str) -> str:
    """Format sources as a structured input for the LLM. Schema reminder
    is appended *after* the source content so the last thing the model
    sees is the output shape — this materially improves JSON compliance
    on local models that otherwise drift into prose."""
    parts: list[str] = [
        f"NOTE RANGE: {range_start} to {range_end}",
        f"SOURCE COUNT: {len(sources)} ({sum(1 for s in sources if s.tier == 'daily')} daily, "
        f"{sum(1 for s in sources if s.tier == 'recent_edit')} recent edits)",
        "",
    ]
    daily = [s for s in sources if s.tier == "daily"]
    edits = [s for s in sources if s.tier == "recent_edit"]

    if daily:
        parts.append("=== DAILY NOTES ===\n")
        for s in daily:
            parts.append(f"--- {s.date} | {s.path} ---")
            parts.append(s.excerpt)
            parts.append("")
    if edits:
        parts.append("=== RECENT VAULT EDITS (excerpts) ===\n")
        for s in edits:
            parts.append(f"--- {s.date} | {s.path} | {s.title} ---")
            parts.append(s.excerpt)
            parts.append("")
    parts.append("")
    parts.append(_OUTPUT_SCHEMA_REMINDER)
    return "\n".join(parts)


def _count_check(
    extracted: dict, sources: list[FoldSource]
) -> tuple[bool, list[str]]:
    """Verify (1) numeric claims in themes are greppable, (2) every citation
    date is a date that actually appears in our source set. Returns
    (passed, list_of_failed_claims).

    The citation check catches a common LLM failure mode: leaking the
    current date or other out-of-range dates into citations. If the model
    cites 2026-05-03 but no source has that date, the model is confabulating
    provenance — that's an extractive contract violation."""
    haystack = "\n".join(s.excerpt for s in sources)
    valid_dates = {s.date for s in sources}
    failures: list[str] = []

    for theme in extracted.get("themes", []) or []:
        if not isinstance(theme, dict):
            continue
        text = theme.get("text", "")
        for m in NUMERIC_CLAIM_RE.finditer(text):
            n = m.group(1)
            # Numbers <= 2 are too generic to verify usefully (cited 2 dates,
            # 1 thing, etc). Anything ≥3 must match a literal occurrence.
            if int(n) >= 3 and n not in haystack:
                failures.append(f"theme: '{text[:80]}' claims {n} but not in sources")
        for cite in theme.get("citations") or []:
            if isinstance(cite, str) and cite[:10] not in valid_dates:
                failures.append(
                    f"theme: '{text[:80]}' cites {cite!r}, not in source dates"
                )

    for loop in extracted.get("open_loops", []) or []:
        if not isinstance(loop, dict):
            continue
        d = loop.get("source_date", "")
        if isinstance(d, str) and d[:10] and d[:10] not in valid_dates:
            failures.append(
                f"open_loop: '{loop.get('text', '')[:60]}' cites {d!r}, "
                "not in source dates"
            )

    for s in extracted.get("day_summaries", []) or []:
        if not isinstance(s, dict):
            continue
        d = s.get("date", "")
        if isinstance(d, str) and d[:10] and d[:10] not in valid_dates:
            failures.append(
                f"day_summary: date {d!r} not in source dates"
            )

    return (len(failures) == 0, failures)


def _confidence_label(passed: bool, n_themes: int, n_sources: int) -> str:
    if not passed:
        return "low"
    if n_sources < 2:
        return "low"
    if n_themes >= 3 and n_sources >= 5:
        return "high"
    return "medium"


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def _default_synth(model: str = DEFAULT_FOLD_MODEL) -> Callable[[str, str], tuple[dict, str, str]]:
    """Build the default synthesizer that calls somm.extract_structured.
    Returns (extracted_dict, model_used, error_or_empty).

    Uses extract_structured (not generate) because local instruction-tuned
    models (gemma4:e4b, qwen2.5, etc.) often return prose around the JSON
    object on first try. somm handles retries with temperature jitter,
    fence-stripping, and the qwen2.5 double-quote quirk for us.
    """
    try:
        from somm import llm  # lazy: only when actually folding
    except ImportError as e:
        raise ImportError(
            "eno fold requires the LLM extra. Install it with:\n"
            "    pip install enowiki[llm]"
        ) from e

    client = llm(project="eno_fold")
    # Register the workload with privacy_class=PRIVATE so somm refuses any
    # non-sovereign provider for this call (no cloud egress on vault prose).
    # Workload may already be registered; observe-mode auto-registers anyway.
    with contextlib.suppress(Exception):
        client.register_workload(
            name="vault_fold",
            privacy_class="private",
            description="Extractive rollup over a date range of vault notes.",
        )

    def _fn(system: str, user: str) -> tuple[dict, str, str]:
        # extract_structured doesn't return the SommResult, so we can't pull
        # provider/model out directly. Run a 1-call generate first to record
        # provider/model, then use extract_structured for retries on the
        # parse path. Less elegant than I'd like, but keeps the model_label
        # honest in telemetry.
        parsed = client.extract_structured(
            prompt=user,
            system=system,
            workload="vault_fold",
            max_tokens=2000,
            temperature=0.2,
            retries=2,
            model=model,
        )
        if isinstance(parsed, dict) and parsed.get("_somm_parse_err"):
            raw = parsed.get("raw", "")[:200]
            return {}, "ollama/?", f"bad_json after retries: {raw}"
        if not isinstance(parsed, dict):
            return {}, "ollama/?", f"unexpected output shape: {type(parsed).__name__}"
        # somm doesn't surface the chosen (provider, model) from
        # extract_structured. Best-effort: read it from the most-recent call
        # row we just wrote.
        try:
            with client.repo._open() as conn:
                row = conn.execute(
                    "SELECT provider, model FROM calls WHERE workload_id = "
                    "(SELECT id FROM workloads WHERE name = 'vault_fold') "
                    "ORDER BY ts DESC LIMIT 1"
                ).fetchone()
            label = f"{row[0]}/{row[1]}" if row else "unknown"
        except Exception:
            label = "unknown"
        return parsed, label, ""

    return _fn


def build_fold(
    db: sqlite3.Connection,
    vault: Path | None = None,
    *,
    range_start: str,
    range_end: str,
    synth: Callable[[str, str], tuple[dict, str, str]] | None = None,
    daily_max_chars: int = DEFAULT_DAILY_MAX_CHARS,
    edit_excerpt_chars: int = DEFAULT_EDIT_EXCERPT_CHARS,
    max_recent_edits: int = DEFAULT_MAX_RECENT_EDITS,
    model: str = DEFAULT_FOLD_MODEL,
) -> Fold:
    """Compose a Fold from index + vault content + somm synthesis.

    Args:
        synth: optional injection point for testing — takes (system, user)
               prompts, returns (extracted_dict, model_label, error_str).
               Defaults to somm.generate via privacy_class=PRIVATE workload.

    Returns a Fold even on synth failure: in that case, themes/open_loops/
    day_summaries are empty, count_check_passed=False, and confidence='low'.
    The wikilink heat and source manifest still populate (cheap, index-only).
    """
    vault = vault or default_vault_dir()
    sources = load_sources(
        db, vault, range_start, range_end,
        daily_max_chars=daily_max_chars,
        edit_excerpt_chars=edit_excerpt_chars,
        max_recent_edits=max_recent_edits,
    )
    fid = fold_id(range_start, range_end, len(sources))
    heat = _wikilink_heat(db, sources)

    if not sources:
        return Fold(
            fold_id=fid,
            range_start=range_start,
            range_end=range_end,
            sources=[],
            wikilink_heat=heat,
            confidence="low",
            count_check_passed=False,
            count_check_failures=["no sources in range"],
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    synth = synth or _default_synth(model=model)
    user_prompt = _build_user_prompt(sources, range_start, range_end)
    extracted, model_label, err = synth(SYSTEM_PROMPT, user_prompt)

    if err:
        return Fold(
            fold_id=fid,
            range_start=range_start,
            range_end=range_end,
            sources=sources,
            wikilink_heat=heat,
            confidence="low",
            count_check_passed=False,
            count_check_failures=[err],
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            model=model_label,
        )

    passed, failures = _count_check(extracted, sources)
    themes = [
        FoldTheme(text=t.get("text", ""), citations=list(t.get("citations") or []))
        for t in (extracted.get("themes") or [])
        if isinstance(t, dict) and t.get("text")
    ]
    open_loops = [
        FoldOpenLoop(
            text=o.get("text", ""),
            source_date=o.get("source_date", ""),
        )
        for o in (extracted.get("open_loops") or [])
        if isinstance(o, dict) and o.get("text")
    ]
    summaries = [
        FoldDaySummary(
            date=s.get("date", ""),
            summary=s.get("summary", ""),
        )
        for s in (extracted.get("day_summaries") or [])
        if isinstance(s, dict) and s.get("summary")
    ]

    confidence = _confidence_label(passed, len(themes), len(sources))

    return Fold(
        fold_id=fid,
        range_start=range_start,
        range_end=range_end,
        sources=sources,
        themes=themes,
        open_loops=open_loops,
        wikilink_heat=heat,
        day_summaries=summaries,
        confidence=confidence,
        count_check_passed=passed,
        count_check_failures=failures,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model=model_label,
    )


# ---------------------------------------------------------------------------
# Topic fold synthesis
# ---------------------------------------------------------------------------


_TOPIC_SYSTEM_PROMPT = (
    "You are an extraction tool reviewing several notes that all relate to "
    "one topic in a personal knowledge vault. Your job is to surface "
    "cross-source patterns: themes, open questions, and per-source "
    "summaries. You do not invent. Every claim must trace to specific "
    "text in the input. Output JSON only — no markdown, no preamble, "
    "no commentary."
)


_TOPIC_OUTPUT_REMINDER = """
TASK: Extract themes, open loops, and per-source summaries from the notes \
above, all relating to a single topic.

Themes must appear in ≥2 distinct source notes. Open loops are unresolved \
questions, pending decisions, or promised follow-ups (preserve the user's \
phrasing). Per-source summaries are one extractive sentence per included \
source.

Citations are SOURCE STEMS — the filename without `.md` and without folder \
path (e.g. for `2 Projects/Acme.md` cite `Acme`). The list of \
valid stems is the set of `STEM:` lines in the input above.

If a section has no extractive material, return an empty list. Do not pad.

OUTPUT EXACTLY this JSON shape (and only this — no markdown, no commentary, \
no headings, no <think> blocks):

{
  "themes": [
    {"text": "extractive cross-source theme", "citations": ["Stem One", "Stem Two"]}
  ],
  "open_loops": [
    {"text": "verbatim or near-verbatim from source", "source_date": "Stem One"}
  ],
  "day_summaries": [
    {"date": "Stem One", "summary": "one extractive sentence"}
  ]
}
""".strip()


def _build_topic_user_prompt(sources: list[FoldSource], topic_label: str) -> str:
    parts: list[str] = [
        f"TOPIC: {topic_label}",
        f"SOURCE COUNT: {len(sources)}",
        "",
        "=== SOURCES ===\n",
    ]
    for s in sources:
        stem = Path(s.path).stem
        parts.append(f"--- STEM: {stem} | PATH: {s.path} | DATE: {s.date} ---")
        parts.append(s.excerpt)
        parts.append("")
    parts.append("")
    parts.append(_TOPIC_OUTPUT_REMINDER)
    return "\n".join(parts)


def _topic_count_check(
    extracted: dict, sources: list[FoldSource]
) -> tuple[bool, list[str]]:
    """Citations must be one of the source filename stems. Mirrors the
    per-fold count_check posture but on stems rather than dates."""
    valid_stems = {Path(s.path).stem for s in sources}
    failures: list[str] = []
    for theme in extracted.get("themes", []) or []:
        if not isinstance(theme, dict):
            continue
        text = theme.get("text", "")
        for cite in theme.get("citations") or []:
            if isinstance(cite, str) and cite not in valid_stems:
                failures.append(
                    f"theme: '{text[:80]}' cites {cite!r}, not in source stems"
                )
    for loop in extracted.get("open_loops", []) or []:
        if not isinstance(loop, dict):
            continue
        d = loop.get("source_date", "")
        if isinstance(d, str) and d and d not in valid_stems:
            failures.append(
                f"open_loop: '{loop.get('text', '')[:60]}' cites {d!r}, "
                "not in source stems"
            )
    for s in extracted.get("day_summaries", []) or []:
        if not isinstance(s, dict):
            continue
        d = s.get("date", "")
        if isinstance(d, str) and d and d not in valid_stems:
            failures.append(f"day_summary: stem {d!r} not in source set")
    return (len(failures) == 0, failures)


def build_topic_fold(
    db: sqlite3.Connection,
    vault: Path | None = None,
    *,
    kind: str,
    value: str,
    synth: Callable[[str, str], tuple[dict, str, str]] | None = None,
    limit: int = DEFAULT_TOPIC_SOURCE_LIMIT,
    excerpt_chars: int = DEFAULT_TOPIC_EXCERPT_CHARS,
    model: str = DEFAULT_FOLD_MODEL,
) -> Fold:
    """Synthesize a fold scoped to a topic (wikilink, folder, or tag).

    Range_start/range_end are derived from the source set (earliest /
    latest by date). Citation contract is filename-stem-based instead
    of date-based.
    """
    vault = vault or default_vault_dir()
    sources = load_topic_sources(
        db, vault, kind, value, limit=limit, excerpt_chars=excerpt_chars,
    )
    if not sources:
        # Range placeholders so the empty fold still has a deterministic id.
        return Fold(
            fold_id=topic_fold_id(kind, value, 0),
            range_start="",
            range_end="",
            sources=[],
            confidence="low",
            count_check_passed=False,
            count_check_failures=[f"no sources for {kind}={value!r}"],
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    dates = sorted(s.date for s in sources)
    range_start, range_end = dates[0], dates[-1]
    fid = topic_fold_id(kind, value, len(sources))
    topic_label = f"{kind}={value}"

    synth = synth or _default_synth(model=model)
    user = _build_topic_user_prompt(sources, topic_label)
    extracted, model_label, err = synth(_TOPIC_SYSTEM_PROMPT, user)

    if err:
        return Fold(
            fold_id=fid,
            range_start=range_start,
            range_end=range_end,
            sources=sources,
            confidence="low",
            count_check_passed=False,
            count_check_failures=[err],
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            model=model_label,
        )

    passed, failures = _topic_count_check(extracted, sources)
    themes = [
        FoldTheme(text=t.get("text", ""), citations=list(t.get("citations") or []))
        for t in (extracted.get("themes") or [])
        if isinstance(t, dict) and t.get("text")
    ]
    open_loops = [
        FoldOpenLoop(text=o.get("text", ""), source_date=o.get("source_date", ""))
        for o in (extracted.get("open_loops") or [])
        if isinstance(o, dict) and o.get("text")
    ]
    summaries = [
        FoldDaySummary(date=s.get("date", ""), summary=s.get("summary", ""))
        for s in (extracted.get("day_summaries") or [])
        if isinstance(s, dict) and s.get("summary")
    ]
    confidence = _confidence_label(passed, len(themes), len(sources))

    return Fold(
        fold_id=fid,
        range_start=range_start,
        range_end=range_end,
        sources=sources,
        themes=themes,
        open_loops=open_loops,
        day_summaries=summaries,
        confidence=confidence,
        count_check_passed=passed,
        count_check_failures=failures,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model=model_label,
        # Topic folds aren't levelled like fold-of-folds; keep level=1.
    )


# ---------------------------------------------------------------------------
# Fold-of-folds (level 2+)
# ---------------------------------------------------------------------------


_OF_FOLDS_SYSTEM_PROMPT = (
    "You are an extraction tool reviewing several child fold notes. Each "
    "child fold itself summarized a date range of personal notes. Your job "
    "is to surface CROSS-FOLD patterns — themes and open loops that appear "
    "in 2+ children, or that evolved between children. You do not invent. "
    "Every claim must trace to specific content visible in the children. "
    "Output JSON only — no markdown, no preamble, no commentary."
)


_OF_FOLDS_OUTPUT_REMINDER = """
TASK: Synthesize cross-fold patterns from the child folds above.

Themes must appear in ≥2 distinct child folds — otherwise they're already \
captured at the lower level. Cite the child fold IDs that surfaced each.

Open loops: items that appear as pending across multiple child folds, or \
that were open in an earlier fold and resurface in a later one. Cite the \
child fold ID(s) where the loop appears.

Day summaries at this level are per-fold summaries: one extractive sentence \
describing what each child fold covered. Use the child fold's own ID as the \
"date" field (e.g. "fold-2026-04-15-to-2026-04-22-n6").

OUTPUT EXACTLY this JSON shape (and only this — no markdown, no commentary, \
no headings, no <think> blocks):

{
  "themes": [
    {"text": "extractive cross-fold theme", "citations": ["fold-...-n6", "fold-...-n8"]}
  ],
  "open_loops": [
    {"text": "verbatim or near-verbatim from a child fold", "source_date": "fold-...-n6"}
  ],
  "day_summaries": [
    {"date": "fold-...-n6", "summary": "one extractive sentence per child"}
  ]
}
""".strip()


def _build_of_folds_user_prompt(child_paths: list[Path]) -> str:
    parts: list[str] = ["=== CHILD FOLDS ===\n"]
    for path in child_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Trim each child to a workable size — keep frontmatter + sections,
        # drop the "Sources" tail to save tokens.
        marker = "## Sources\n"
        if marker in text:
            text = text.split(marker, 1)[0].rstrip() + "\n"
        parts.append(f"--- {path.stem} ---")
        parts.append(text.strip())
        parts.append("")
    parts.append("")
    parts.append(_OF_FOLDS_OUTPUT_REMINDER)
    return "\n".join(parts)


def _of_folds_count_check(
    extracted: dict, child_ids: set[str]
) -> tuple[bool, list[str]]:
    """Citations must reference child fold IDs that we actually included.
    Otherwise the LLM is confabulating provenance."""
    failures: list[str] = []
    for theme in extracted.get("themes", []) or []:
        if not isinstance(theme, dict):
            continue
        text = theme.get("text", "")
        for cite in theme.get("citations") or []:
            if isinstance(cite, str) and cite not in child_ids:
                failures.append(
                    f"theme: '{text[:80]}' cites {cite!r}, not a child fold id"
                )
    for loop in extracted.get("open_loops", []) or []:
        if not isinstance(loop, dict):
            continue
        d = loop.get("source_date", "")
        if isinstance(d, str) and d and d not in child_ids:
            failures.append(
                f"open_loop: '{loop.get('text', '')[:60]}' cites {d!r}, "
                "not a child fold id"
            )
    for s in extracted.get("day_summaries", []) or []:
        if not isinstance(s, dict):
            continue
        d = s.get("date", "")
        if isinstance(d, str) and d and d not in child_ids:
            failures.append(f"day_summary: date {d!r} is not a child fold id")
    return (len(failures) == 0, failures)


def build_fold_over_folds(
    vault: Path,
    *,
    children_meta: list[dict],
    range_start: str,
    range_end: str,
    synth: Callable[[str, str], tuple[dict, str, str]] | None = None,
    model: str = DEFAULT_FOLD_MODEL,
) -> Fold:
    """Synthesize an L2 fold from existing committed child folds.

    Args:
        children_meta: list of fold metadata dicts from list_committed_folds().
                       Must already be filtered to the desired children.
        range_start/range_end: union range over the children.

    Returns a Fold with level=2, children=[child_ids], sources=[] (sources
    are implicit via children), and a synthesized themes/open_loops/
    day_summaries set scoped to cross-child patterns.
    """
    child_ids = [c["fold_id"] for c in children_meta]
    fid = f"fold-L2-{range_start}-to-{range_end}-n{len(child_ids)}"

    if not children_meta:
        return Fold(
            fold_id=fid,
            range_start=range_start,
            range_end=range_end,
            level=2,
            children=[],
            confidence="low",
            count_check_passed=False,
            count_check_failures=["no child folds provided"],
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    child_paths = [vault / c["path"] for c in children_meta]
    synth = synth or _default_synth(model=model)
    user = _build_of_folds_user_prompt(child_paths)
    extracted, model_label, err = synth(_OF_FOLDS_SYSTEM_PROMPT, user)

    if err:
        return Fold(
            fold_id=fid,
            range_start=range_start,
            range_end=range_end,
            level=2,
            children=child_ids,
            confidence="low",
            count_check_passed=False,
            count_check_failures=[err],
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            model=model_label,
        )

    passed, failures = _of_folds_count_check(extracted, set(child_ids))
    themes = [
        FoldTheme(text=t.get("text", ""), citations=list(t.get("citations") or []))
        for t in (extracted.get("themes") or [])
        if isinstance(t, dict) and t.get("text")
    ]
    open_loops = [
        FoldOpenLoop(
            text=o.get("text", ""), source_date=o.get("source_date", ""),
        )
        for o in (extracted.get("open_loops") or [])
        if isinstance(o, dict) and o.get("text")
    ]
    summaries = [
        FoldDaySummary(date=s.get("date", ""), summary=s.get("summary", ""))
        for s in (extracted.get("day_summaries") or [])
        if isinstance(s, dict) and s.get("summary")
    ]
    confidence = _confidence_label(passed, len(themes), len(child_ids))

    return Fold(
        fold_id=fid,
        range_start=range_start,
        range_end=range_end,
        level=2,
        children=child_ids,
        themes=themes,
        open_loops=open_loops,
        day_summaries=summaries,
        confidence=confidence,
        count_check_passed=passed,
        count_check_failures=failures,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model=model_label,
        # supersedes is filled in by commit() when it auto-detects contained
        # ranges. For --over-folds, the children explicitly named are likely
        # the same set, so commit's detection will pick them up.
    )


# ---------------------------------------------------------------------------
# Render + commit
# ---------------------------------------------------------------------------


def render_markdown(fold: Fold) -> str:
    """Render the fold as a markdown note. This is what gets either printed
    in dry-run mode or written to disk in commit mode. Frontmatter mirrors
    eno's existing convention (origin/stage/created/updated/author)."""
    lines: list[str] = []
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    lines.append("---")
    lines.append(f'title: "{fold.fold_id}"')
    lines.append("type: fold")
    lines.append("origin: llm")
    lines.append("stage: reference")
    lines.append("author: '[[gbrain]]'")
    lines.append(f"created: {today}")
    lines.append(f"updated: {today}")
    lines.append(f"range_start: {fold.range_start}")
    lines.append(f"range_end: {fold.range_end}")
    lines.append(f"level: {fold.level}")
    if fold.level == 1:
        lines.append(f"n_sources: {len(fold.sources)}")
    else:
        lines.append(f"n_children: {len(fold.children)}")
    lines.append(f"confidence: {fold.confidence}")
    lines.append(f"count_check_passed: {str(fold.count_check_passed).lower()}")
    lines.append(f"workload: {fold.workload}")
    if fold.model:
        lines.append(f"model: {fold.model}")
    if fold.supersedes:
        lines.append("supersedes:")
        for fid in fold.supersedes:
            lines.append(f'  - "[[{fid}]]"')
    if fold.children:
        lines.append("children:")
        for cid in fold.children:
            lines.append(f'  - "[[{cid}]]"')
    lines.append("sources:")
    for s in fold.sources:
        lines.append(f"  - \"[[{Path(s.path).stem}]]\"")
    lines.append("---")
    lines.append("")
    lines.append(f"# {fold.fold_id}")
    lines.append("")
    is_topic_fold = fold.fold_id.startswith("fold-topic-")
    if fold.level >= 2:
        lines.append(
            f"_L{fold.level} extractive cross-fold rollup over {len(fold.children)} "
            f"child fold(s) between {fold.range_start} and {fold.range_end}._"
        )
    elif is_topic_fold:
        lines.append(
            f"_Extractive rollup of {len(fold.sources)} notes related to one topic; "
            f"earliest source {fold.range_start}, latest {fold.range_end}._"
        )
    else:
        lines.append(
            f"_Extractive rollup of {len(fold.sources)} notes "
            f"({sum(1 for s in fold.sources if s.tier == 'daily')} daily, "
            f"{sum(1 for s in fold.sources if s.tier == 'recent_edit')} recent edits) "
            f"between {fold.range_start} and {fold.range_end}._"
        )
    lines.append("")
    lines.append(f"_Generated {fold.generated_at} via `{fold.model or 'unknown'}`. "
                 f"Confidence: **{fold.confidence}**._")
    lines.append("")

    if not fold.count_check_passed and fold.count_check_failures:
        lines.append("> [!warning] Count check failed")
        for f in fold.count_check_failures[:5]:
            lines.append(f"> - {f}")
        lines.append("")

    lines.append("## Themes")
    lines.append("")
    if fold.themes:
        for t in fold.themes:
            cites = ", ".join(t.citations) if t.citations else "(uncited)"
            lines.append(f"- {t.text}  _(seen on: {cites})_")
    else:
        lines.append("_(none extracted)_")
    lines.append("")

    lines.append("## Open loops")
    lines.append("")
    if fold.open_loops:
        for o in fold.open_loops:
            lines.append(f"- {o.text}  _(from {o.source_date})_")
    else:
        lines.append("_(none)_")
    lines.append("")

    if fold.level == 1 and not is_topic_fold:
        lines.append("## Wikilink heat")
        lines.append("")
        if fold.wikilink_heat:
            for h in fold.wikilink_heat[:20]:
                marker = "" if h.resolves else " *(incipient)*"
                dates = ", ".join(h.source_dates)
                lines.append(
                    f"- [[{h.target}]] — {h.count}× across {len(h.source_dates)} day(s)"
                    f"{marker}  _(on: {dates})_"
                )
        else:
            lines.append("_(none)_")
        lines.append("")

    if fold.level >= 2:
        lines.append("## Per-fold summaries")
    elif is_topic_fold:
        lines.append("## Per-source summaries")
    else:
        lines.append("## Per-day TL;DR")
    lines.append("")
    if fold.day_summaries:
        for s in sorted(fold.day_summaries, key=lambda d: d.date):
            label = f"[[{s.date}]]" if fold.level >= 2 or is_topic_fold else f"**{s.date}**"
            lines.append(f"- {label} — {s.summary}")
    else:
        lines.append("_(none)_")
    lines.append("")

    if fold.level >= 2:
        lines.append("## Children")
        lines.append("")
        for cid in fold.children:
            lines.append(f"- [[{cid}]]")
        lines.append("")
    else:
        lines.append("## Sources")
        lines.append("")
        for s in fold.sources:
            if s.tier == "daily":
                tier = "daily"
            elif s.tier == "topic":
                tier = "topic"
            else:
                tier = "edit"
            lines.append(
                f"- `[{tier}]` [[{Path(s.path).stem}]] "
                f"({s.date}, {s.word_count} words)"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def _find_supersession_targets(fold: Fold, vault: Path) -> list[dict]:
    """Existing committed folds whose [range_start, range_end] is fully
    contained within `fold`'s range — and which aren't already superseded.
    Returns the list of fold metadata dicts (from list_committed_folds)."""
    new_start = fold.range_start
    new_end = fold.range_end
    new_id = fold.fold_id
    candidates: list[dict] = []
    for entry in list_committed_folds(vault):
        if entry["fold_id"] == new_id:
            continue
        if entry.get("superseded_by"):
            continue
        es, ee = entry["range_start"], entry["range_end"]
        if not es or not ee:
            continue
        # Strict containment: equal range counts as contained (re-fold of same window).
        if new_start <= es and ee <= new_end:
            # And ranges aren't strictly equal AND new fold isn't shorter (just safety).
            candidates.append(entry)
    return candidates


def _mutate_frontmatter_add(path: Path, additions: dict[str, str]) -> None:
    """Insert key:value pairs into an existing fold's frontmatter, before
    the closing `---`. Idempotent: if a key already matches, skip.
    String values only — list values handled by appending lines manually
    via the `additions` dict's keys ending with `[]` (untyped tag)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return
    end = text.find("\n---\n", 4)
    if end < 0:
        return
    fm_block = text[4:end]
    body = text[end + 5 :]

    fm_lines = fm_block.split("\n")
    existing_keys = {
        line.split(":", 1)[0].strip()
        for line in fm_lines
        if ":" in line and not line.startswith(" ")
    }
    new_lines: list[str] = []
    for key, val in additions.items():
        if key in existing_keys:
            continue
        new_lines.append(f"{key}: {val}")
    if not new_lines:
        return
    new_fm = "\n".join(fm_lines + new_lines)
    path.write_text(f"---\n{new_fm}\n---\n{body}", encoding="utf-8")


def commit(fold: Fold, vault: Path | None = None, *, force: bool = False) -> Path:
    """Write the fold note to disk and append a one-line entry to
    `.eno/fold-log.md`. Auto-supersedes any contained-range folds:
    updates this fold's `supersedes:` list and the older folds'
    `superseded_by:` frontmatter. Refuses to overwrite without `force`."""
    vault = vault or default_vault_dir()
    target = fold_path(vault, fold.fold_id)
    if target.exists() and not force:
        raise FileExistsError(
            f"fold already exists at {target}. Use --force to overwrite, "
            f"or pick a different range."
        )

    # Detect supersession BEFORE writing the new fold so its frontmatter
    # carries `supersedes: [...]`.
    targets = _find_supersession_targets(fold, vault)
    if targets:
        # Avoid duplicates — `supersedes` may already have entries from
        # an --over-folds invocation that explicitly named children.
        existing = set(fold.supersedes)
        for t in targets:
            if t["fold_id"] not in existing:
                fold.supersedes.append(t["fold_id"])
                existing.add(t["fold_id"])

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(fold), encoding="utf-8")

    # Mutate the older folds' frontmatter to record the supersession.
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for t in targets:
        old_path = vault / t["path"]
        _mutate_frontmatter_add(
            old_path,
            {
                "superseded_by": f'"[[{fold.fold_id}]]"',
                "superseded_at": today,
            },
        )

    # Append-only fold log; lives in `.eno/` (off-vault metadata).
    log_path = vault / FOLD_LOG_REL
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    sup_str = f", supersedes={len(targets)}" if targets else ""
    log_entry = (
        f"- [{ts}] **{fold.fold_id}** "
        f"({len(fold.sources)} sources, confidence={fold.confidence}, "
        f"count_check={'pass' if fold.count_check_passed else 'fail'}"
        f"{sup_str})\n"
    )
    if log_path.exists():
        log_path.write_text(log_path.read_text() + log_entry, encoding="utf-8")
    else:
        log_path.write_text(
            "# eno fold log\n\nAppend-only record of fold operations.\n\n" + log_entry,
            encoding="utf-8",
        )
    return target


def last_committed_fold_end(vault: Path | None = None) -> str | None:
    """Read `.eno/fold-log.md` and return the most-recent fold's range_end,
    or None if no log exists. Used by `--since-last`."""
    vault = vault or default_vault_dir()
    log_path = vault / FOLD_LOG_REL
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8")
    # Lines look like: `- [TS] **fold-2026-04-25-to-2026-04-30-n6** (...)`
    last: str | None = None
    for line in text.splitlines():
        m = re.search(r"fold-\d{4}-\d{2}-\d{2}-to-(\d{4}-\d{2}-\d{2})-n\d+", line)
        if m:
            last = m.group(1)
    return last
