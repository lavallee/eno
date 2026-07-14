"""Structural gardener.

Classifies broken wikilinks into two buckets:
  - drift candidates — target fuzzy-matches an existing note (real bug class)
  - concept candidates — target matches nothing (intentional groundwork)

Detects near-duplicate notes by title similarity. Gathers resurfacing,
stubs, and stale via existing query primitives. Renders a single dated
markdown report into `<vault>/9 Vault Health/`.

The drift classifier uses stdlib difflib.SequenceMatcher with cheap
prefilters (length ratio, real_quick_ratio, quick_ratio) before the
real .ratio() call. ~20s on a 1000-note vault.
"""

from __future__ import annotations

import difflib
import re
import sqlite3
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from . import queries
from .views import (
    ConceptCandidate,
    DriftCandidate,
    DuplicatePair,
    GardenReport,
)

DRIFT_THRESHOLD = 0.85
DUPLICATE_THRESHOLD = 0.90
LENGTH_FILTER_RATIO = 0.3
# Titles that appear on 3+ notes are placeholder defaults (e.g. "Untitled
# Research" from a frontmatter template) — skip them in duplicate detection.
PLACEHOLDER_TITLE_THRESHOLD = 3

# Folders whose broken links are typically auto-generated (not user
# concept-gestures) and shouldn't pollute the concept list. Notes
# inside these paths get skipped during link classification.
REPORT_FOLDER_PATTERNS = (
    re.compile(r"^9 Vault Health/"),
    re.compile(r"/reports?/"),
    re.compile(r"^\.eno/"),
)


def _is_report_path(path: str) -> bool:
    return any(p.search(path) for p in REPORT_FOLDER_PATTERNS)


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _link_targets(db: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Build all (normalized_key, original_path, display_title) tuples that a
    broken link could possibly resolve to: basenames, titles, and aliases."""
    out: list[tuple[str, str, str]] = []
    title_by_path: dict[str, str] = {}
    for path, title in db.execute("SELECT path, title FROM notes"):
        title_by_path[path] = title
        out.append((_normalize(Path(path).stem), path, title))
        out.append((_normalize(title), path, title))
    for path, alias in db.execute("SELECT path, alias FROM aliases"):
        title = title_by_path.get(path, path)
        out.append((_normalize(alias), path, title))
    # Dedupe identical (key, path) pairs but keep the first title we saw
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str, str]] = []
    for key, path, title in out:
        if not key:
            continue
        ident = (key, path)
        if ident in seen:
            continue
        seen.add(ident)
        deduped.append((key, path, title))
    return deduped


def _best_match(
    target_norm: str, candidates: list[tuple[str, str, str]], threshold: float
) -> tuple[float, str, str]:
    best_score = 0.0
    best_path = ""
    best_title = ""
    for cand_norm, cand_path, cand_title in candidates:
        if not cand_norm:
            continue
        if (
            abs(len(target_norm) - len(cand_norm))
            > max(len(target_norm), len(cand_norm)) * LENGTH_FILTER_RATIO
        ):
            continue
        sm = difflib.SequenceMatcher(None, target_norm, cand_norm, autojunk=False)
        if sm.real_quick_ratio() < threshold:
            continue
        if sm.quick_ratio() < threshold:
            continue
        score = sm.ratio()
        if score > best_score:
            best_score = score
            best_path = cand_path
            best_title = cand_title
    return best_score, best_path, best_title


def classify_broken_links(
    db: sqlite3.Connection,
    *,
    drift_threshold: float = DRIFT_THRESHOLD,
    skip_report_folders: bool = True,
) -> tuple[list[DriftCandidate], list[ConceptCandidate]]:
    by_target: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for src_path, target_text, line_no in db.execute(
        "SELECT src_path, target_text, line_no FROM links WHERE target_path IS NULL"
    ):
        if skip_report_folders and _is_report_path(src_path):
            continue
        by_target[target_text].append((src_path, line_no))

    candidates = _link_targets(db)
    drift: list[DriftCandidate] = []
    concepts: list[ConceptCandidate] = []

    for target_text, sources in by_target.items():
        target_norm = _normalize(target_text)
        if not target_norm:
            continue
        score, best_path, best_title = _best_match(
            target_norm, candidates, drift_threshold
        )
        sources_dicts = [{"src_path": s, "line_no": ln} for s, ln in sources]
        if score >= drift_threshold and best_path:
            drift.append(
                DriftCandidate(
                    target_text=target_text,
                    sources=sources_dicts,
                    suggested_path=best_path,
                    suggested_title=best_title,
                    score=round(score, 3),
                )
            )
        else:
            concepts.append(
                ConceptCandidate(
                    target_text=target_text,
                    sources=sources_dicts,
                    mention_count=len(sources),
                )
            )

    drift.sort(key=lambda d: -d.score)
    concepts.sort(key=lambda c: -c.mention_count)
    return drift, concepts


def find_duplicates(
    db: sqlite3.Connection, *, threshold: float = DUPLICATE_THRESHOLD
) -> list[DuplicatePair]:
    rows = db.execute("SELECT path, title FROM notes ORDER BY path").fetchall()
    title_counts: dict[str, int] = defaultdict(int)
    for _, title in rows:
        title_counts[title] += 1
    placeholder_titles = {
        t for t, c in title_counts.items() if c >= PLACEHOLDER_TITLE_THRESHOLD
    }
    norms = [
        (p, t, _normalize(t))
        for p, t in rows
        if t not in placeholder_titles
    ]
    pairs: list[DuplicatePair] = []
    for i, (path_a, title_a, norm_a) in enumerate(norms):
        if not norm_a:
            continue
        for path_b, title_b, norm_b in norms[i + 1:]:
            if not norm_b:
                continue
            if (
                abs(len(norm_a) - len(norm_b))
                > max(len(norm_a), len(norm_b)) * LENGTH_FILTER_RATIO
            ):
                continue
            sm = difflib.SequenceMatcher(None, norm_a, norm_b, autojunk=False)
            if sm.real_quick_ratio() < threshold:
                continue
            if sm.quick_ratio() < threshold:
                continue
            score = sm.ratio()
            if score >= threshold:
                pairs.append(
                    DuplicatePair(
                        path_a=path_a,
                        path_b=path_b,
                        title_a=title_a,
                        title_b=title_b,
                        score=round(score, 3),
                    )
                )
    pairs.sort(key=lambda p: -p.score)
    return pairs


def garden(
    db: sqlite3.Connection,
    *,
    folder: str | None = None,
    resurfacing_min_words: int = 1000,
    stub_max_words: int = 80,
    stale_days: int = 180,
    drift_threshold: float = DRIFT_THRESHOLD,
    duplicate_threshold: float = DUPLICATE_THRESHOLD,
) -> GardenReport:
    started = time.monotonic()
    drift, concepts = classify_broken_links(db, drift_threshold=drift_threshold)
    duplicates = find_duplicates(db, threshold=duplicate_threshold)
    resurfacing = queries.orphans(
        db, folder=folder, min_words=resurfacing_min_words, limit=20
    )
    stubs = queries.stubs(db, max_words=stub_max_words, limit=20)
    stale = queries.stale(db, older_than_days=stale_days, limit=20)
    elapsed = time.monotonic() - started
    return GardenReport(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        resurfacing=resurfacing,
        concepts=concepts,
        drift=drift,
        stubs=stubs,
        stale=stale,
        duplicates=duplicates,
        stats={
            "elapsed_s": round(elapsed, 2),
            "drift_count": len(drift),
            "concept_count": len(concepts),
            "duplicate_count": len(duplicates),
        },
    )


# ---- markdown rendering ---------------------------------------------------


def _wikilink(path: str, title: str | None = None) -> str:
    """Build a path-style Obsidian wikilink (no .md suffix), with optional alias."""
    target = path[:-3] if path.endswith(".md") else path
    if title and title != Path(target).stem:
        return f"[[{target}|{title}]]"
    return f"[[{target}]]"


def render_garden_report(report: GardenReport) -> str:
    import yaml

    fm = {
        "kind": "eno-garden-report",
        "generated_at": report.generated_at,
        "stats": report.stats,
        "counts": {
            "resurfacing": len(report.resurfacing),
            "concepts": len(report.concepts),
            "drift": len(report.drift),
            "duplicates": len(report.duplicates),
            "stubs": len(report.stubs),
            "stale": len(report.stale),
        },
    }
    fm_text = yaml.safe_dump(
        fm, sort_keys=False, default_flow_style=False, allow_unicode=True, width=10**9
    ).rstrip()

    lines: list[str] = []
    lines.append("---")
    lines.append(fm_text)
    lines.append("---")
    lines.append("")
    lines.append(f"# Vault Health — Garden Report — {report.generated_at}")
    lines.append("")
    lines.append(
        f"Resurfacing: **{len(report.resurfacing)}**, "
        f"concept candidates: **{report.stats.get('concept_count', 0)}**, "
        f"drift candidates: **{report.stats.get('drift_count', 0)}**, "
        f"stubs: **{len(report.stubs)}**, stale: **{len(report.stale)}**, "
        f"possible duplicates: **{report.stats.get('duplicate_count', 0)}**."
    )
    lines.append(f"Generated in {report.stats.get('elapsed_s', 0)}s.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Resurfacing — biggest leverage section, goes first.
    lines.append("## Resurfacing — substantial notes nothing links to")
    lines.append("")
    if not report.resurfacing:
        lines.append("_(none)_")
    else:
        lines.append(
            "_Forgotten gold by word count. Not bugs — just buried. "
            "Worth a re-read or a link from somewhere active._"
        )
        lines.append("")
        for r in report.resurfacing:
            lines.append(f"- {_wikilink(r.path, r.title)} — {r.word_count:,} words")
    lines.append("")

    # Concept candidates (incipient links) — what the user has gestured at.
    lines.append("## Concept candidates — wikilinks you've gestured at")
    lines.append("")
    if not report.concepts:
        lines.append("_(none)_")
    else:
        lines.append(
            "_These wikilink targets don't yet exist as notes. Each is "
            "groundwork for a future page — not bugs to fix; concepts to "
            "consider drafting when ready._"
        )
        lines.append("")
        for c in report.concepts[:30]:
            label = "1 mention" if c.mention_count == 1 else f"{c.mention_count} mentions"
            srcs = ", ".join(_wikilink(s["src_path"]) for s in c.sources[:3])
            more = "" if len(c.sources) <= 3 else f" + {len(c.sources) - 3} more"
            lines.append(f"- **`[[{c.target_text}]]`** — {label} from {srcs}{more}")
    lines.append("")

    # Drift candidates — the actual bugs.
    lines.append("## Drift candidates — wikilinks that should resolve but don't")
    lines.append("")
    if not report.drift:
        lines.append("_(none)_")
    else:
        lines.append(
            "_These almost match an existing note (em-dash drift, casing, "
            "trailing punctuation). One-line fix to repair each backlink._"
        )
        lines.append("")
        for d in report.drift[:30]:
            mentions = f"{len(d.sources)} ref{'s' if len(d.sources) > 1 else ''}"
            lines.append(
                f"- `[[{d.target_text}]]` → "
                f"{_wikilink(d.suggested_path, d.suggested_title)} "
                f"({d.score:.0%} match, {mentions})"
            )
    lines.append("")

    # Possible duplicates
    lines.append("## Possible duplicates — similar titles")
    lines.append("")
    if not report.duplicates:
        lines.append("_(none)_")
    else:
        lines.append("_Notes whose titles are close enough to suggest overlap._")
        lines.append("")
        for d in report.duplicates[:20]:
            lines.append(
                f"- {_wikilink(d.path_a, d.title_a)} ↔ "
                f"{_wikilink(d.path_b, d.title_b)} ({d.score:.0%})"
            )
    lines.append("")

    lines.append("## Stubs — short notes with no outbound links")
    lines.append("")
    if not report.stubs:
        lines.append("_(none)_")
    else:
        for s in report.stubs[:20]:
            lines.append(f"- {_wikilink(s.path, s.title)} ({s.word_count} words)")
    lines.append("")

    lines.append("## Stale — not touched in a while")
    lines.append("")
    if not report.stale:
        lines.append("_(none)_")
    else:
        for s in report.stale[:20]:
            lines.append(f"- {_wikilink(s.path, s.title)} ({s.word_count} words)")
    lines.append("")

    return "\n".join(lines) + "\n"


def default_garden_report_path(vault: Path) -> Path:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return vault / "9 Vault Health" / f"{today}-garden.md"
