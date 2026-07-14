"""Tests for the structural gardener: link classifier, duplicate detection,
report orchestration, markdown rendering."""

import time
from pathlib import Path

from eno.config import index_path
from eno.db import open_index
from eno.garden import (
    classify_broken_links,
    find_duplicates,
    garden,
    render_garden_report,
)
from eno.indexer import index_vault


def _write(vault: Path, rel: str, content: str, mtime: float | None = None) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))


def _open(vault: Path):
    return open_index(index_path(vault))


# ---- classify_broken_links ----------------------------------------------


def test_classify_drift_when_target_fuzzy_matches(tmp_path: Path):
    _write(tmp_path, "GTM Framework Speed and Cost.md", "# GTM Framework Speed and Cost\n")
    _write(
        tmp_path,
        "Source.md",
        "# Source\n\nsee [[GTM Framework — Speed and Cost]]\n",
    )
    index_vault(tmp_path)
    drift, concepts = classify_broken_links(_open(tmp_path))
    assert len(drift) == 1
    assert drift[0].target_text == "GTM Framework — Speed and Cost"
    assert drift[0].suggested_path == "GTM Framework Speed and Cost.md"
    assert drift[0].score >= 0.85
    assert concepts == []


def test_classify_concept_when_no_match(tmp_path: Path):
    _write(tmp_path, "Real.md", "# Real\n")
    _write(
        tmp_path,
        "Source.md",
        "# Source\n\nlink to [[Some Future Concept I Have Not Written]]\n",
    )
    index_vault(tmp_path)
    drift, concepts = classify_broken_links(_open(tmp_path))
    assert drift == []
    assert len(concepts) == 1
    assert concepts[0].target_text == "Some Future Concept I Have Not Written"
    assert concepts[0].mention_count == 1


def test_classify_dedupes_by_target(tmp_path: Path):
    _write(tmp_path, "A.md", "# A\n\n[[Concept X]]\n")
    _write(tmp_path, "B.md", "# B\n\n[[Concept X]] and [[Concept X]] again\n")
    _write(tmp_path, "C.md", "# C\n\n[[Concept X]]\n")
    index_vault(tmp_path)
    drift, concepts = classify_broken_links(_open(tmp_path))
    assert len(concepts) == 1
    assert concepts[0].mention_count == 4  # 1 + 2 + 1


def test_classify_skips_report_folders(tmp_path: Path):
    _write(tmp_path, "Real.md", "# Real\n")
    _write(
        tmp_path,
        "9 Vault Health/2026-04-30-garden.md",
        "# Garden\n\n[[Future Concept]]\n",
    )
    _write(
        tmp_path,
        "crow/reports/segments.md",
        "# Segments\n\n[[Auto Generated]]\n",
    )
    index_vault(tmp_path)
    drift, concepts = classify_broken_links(_open(tmp_path))
    # Both broken links should be filtered out (report folders)
    assert drift == []
    assert concepts == []


def test_classify_resolves_via_alias(tmp_path: Path):
    _write(tmp_path, "RealNote.md", "---\naliases: [Foo Bar Baz]\n---\n# RealNote\n")
    _write(tmp_path, "Caller.md", "# Caller\n\n[[Foo Bar Baz!]]\n")
    index_vault(tmp_path)
    drift, concepts = classify_broken_links(_open(tmp_path))
    # "Foo Bar Baz!" → "Foo Bar Baz" alias of RealNote.md (high similarity)
    assert len(drift) == 1
    assert drift[0].suggested_path == "RealNote.md"


# ---- find_duplicates -----------------------------------------------------


def test_find_duplicates(tmp_path: Path):
    _write(tmp_path, "Decision Themes.md", "# Decision Themes\n")
    _write(tmp_path, "Decision Theme.md", "# Decision Theme\n")
    _write(tmp_path, "Unrelated.md", "# Unrelated\n")
    index_vault(tmp_path)
    pairs = find_duplicates(_open(tmp_path))
    assert len(pairs) == 1
    assert {pairs[0].path_a, pairs[0].path_b} == {
        "Decision Themes.md",
        "Decision Theme.md",
    }


def test_find_duplicates_empty_for_distinct_titles(tmp_path: Path):
    _write(tmp_path, "Apples.md", "# Apples\n")
    _write(tmp_path, "Bananas.md", "# Bananas\n")
    index_vault(tmp_path)
    assert find_duplicates(_open(tmp_path)) == []


def test_find_duplicates_skips_placeholder_titles(tmp_path: Path):
    """Notes whose title is shared by 3+ notes (template default) shouldn't pair."""
    for i in range(4):
        _write(
            tmp_path,
            f"note-{i}.md",
            "---\ntitle: Untitled Research\n---\n# Untitled Research\n",
        )
    index_vault(tmp_path)
    assert find_duplicates(_open(tmp_path)) == []


# ---- garden orchestrator -------------------------------------------------


def test_garden_assembles_all_sections(tmp_path: Path):
    long_ago = time.time() - 365 * 86400
    _write(tmp_path, "Big.md", "# Big\n\n" + ("word " * 1500))
    _write(tmp_path, "Stub.md", "# Stub\n", mtime=long_ago)
    _write(
        tmp_path,
        "WithLinks.md",
        "# WithLinks\n\n[[Real Note Here]] [[Future Concept]]\n",
    )
    _write(tmp_path, "Real Note Hare.md", "# Real Note Hare\n")  # near-match for drift
    index_vault(tmp_path)

    db = _open(tmp_path)
    rep = garden(db)
    assert "Big.md" in [r.path for r in rep.resurfacing]
    assert "Stub.md" in [s.path for s in rep.stubs]
    assert "Stub.md" in [s.path for s in rep.stale]  # 365d old + no stage
    # Drift OR concept — depends on similarity score; the important thing is
    # that broken links were classified.
    classified = len(rep.drift) + len(rep.concepts)
    assert classified == 2


def test_garden_stats_populated(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n")
    index_vault(tmp_path)
    rep = garden(_open(tmp_path))
    assert "elapsed_s" in rep.stats
    assert rep.generated_at  # non-empty


# ---- render_garden_report ------------------------------------------------


def test_render_includes_all_sections(tmp_path: Path):
    _write(tmp_path, "Big.md", "# Big Note\n\n" + ("word " * 1500))
    _write(tmp_path, "X.md", "# X\n\n[[Future Concept]]\n")
    index_vault(tmp_path)
    rep = garden(_open(tmp_path))
    out = render_garden_report(rep)

    assert "Garden Report" in out
    assert "## Resurfacing" in out
    assert "## Concept candidates" in out
    assert "## Drift candidates" in out
    assert "## Possible duplicates" in out
    assert "## Stubs" in out
    assert "## Stale" in out
    # Resurfacing entry rendered as wikilink
    assert "[[Big|Big Note]]" in out
    # Concept candidate rendered with target_text
    assert "Future Concept" in out


def test_render_handles_empty_sections(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n")
    index_vault(tmp_path)
    rep = garden(_open(tmp_path))
    out = render_garden_report(rep)
    # Empty sections render with "(none)" — not blank
    assert out.count("_(none)_") >= 4
