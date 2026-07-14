"""Tests for fold.build_fold + commit.

Stubs the LLM synth function so tests don't need ollama. Verifies discipline:
deterministic ID, two-tier source loading, count-check enforcement,
extractive citation, refusal-on-existing without force.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from eno import fold
from eno.config import index_path
from eno.db import open_index
from eno.indexer import index_vault


def _write(vault: Path, rel: str, content: str, mtime: float | None = None) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    if mtime is not None:
        os.utime(p, (mtime, mtime))


def _open(vault: Path):
    return open_index(index_path(vault))


def _stub_synth(payload: dict, model_label: str = "stub-ollama/test"):
    """Build a synth function that always returns the given payload."""
    def _fn(system: str, user: str) -> tuple[dict, str, str]:
        return payload, model_label, ""
    return _fn


def _stub_synth_failure(error: str = "ollama unreachable"):
    def _fn(system: str, user: str) -> tuple[dict, str, str]:
        return {}, "stub/none", error
    return _fn


def test_fold_id_deterministic():
    a = fold.fold_id("2026-04-01", "2026-04-07", 5)
    b = fold.fold_id("2026-04-01", "2026-04-07", 5)
    c = fold.fold_id("2026-04-01", "2026-04-07", 6)
    assert a == b == "fold-2026-04-01-to-2026-04-07-n5"
    assert a != c


def test_load_sources_picks_dailies_in_range(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-25.md",
           "---\nupdated: '2026-04-25'\n---\n# 2026-04-25\n\nday note text\n")
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# 2026-04-29\n\nlater day text\n")
    _write(tmp_path, "z Daily Notes/2026-05-10.md",  # outside range
           "---\nupdated: '2026-05-10'\n---\n# 2026-05-10\n\noutside\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    sources = fold.load_sources(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-30",
    )
    paths = [s.path for s in sources]
    assert "z Daily Notes/2026-04-25.md" in paths
    assert "z Daily Notes/2026-04-29.md" in paths
    assert "z Daily Notes/2026-05-10.md" not in paths
    assert all(s.tier == "daily" for s in sources)


def test_load_sources_picks_recent_edits_outside_daily(tmp_path):
    """Notes elsewhere with mtime in range get pulled as tier='recent_edit'."""
    in_range = time.mktime(time.strptime("2026-04-29", "%Y-%m-%d"))
    out_of_range = time.mktime(time.strptime("2026-03-01", "%Y-%m-%d"))
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\ntext\n", mtime=in_range)
    _write(tmp_path, "2 Projects/Acme.md",
           "# Acme\n\nproject body content here\n", mtime=in_range)
    _write(tmp_path, "Old Note.md",
           "# Old\n\nuntouched\n", mtime=out_of_range)
    index_vault(tmp_path)
    db = _open(tmp_path)

    sources = fold.load_sources(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-30",
    )
    by_tier = {s.path: s.tier for s in sources}
    assert by_tier.get("z Daily Notes/2026-04-29.md") == "daily"
    assert by_tier.get("2 Projects/Acme.md") == "recent_edit"
    assert "Old Note.md" not in by_tier


def test_load_sources_skips_fold_output_dir(tmp_path):
    """Folds shouldn't fold over their own output."""
    in_range = time.mktime(time.strptime("2026-04-29", "%Y-%m-%d"))
    _write(tmp_path, "9 Vault Health/folds/fold-2026-04-15-to-2026-04-22-n5.md",
           "# Old fold\n\nbody\n", mtime=in_range)
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\ntext\n", mtime=in_range)
    index_vault(tmp_path)
    db = _open(tmp_path)

    sources = fold.load_sources(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-30",
    )
    paths = [s.path for s in sources]
    assert all(not p.startswith("9 Vault Health/folds/") for p in paths)


def test_build_fold_passes_count_check_when_numbers_in_sources(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\nthinking about 5 strategy options\n")
    _write(tmp_path, "z Daily Notes/2026-04-30.md",
           "---\nupdated: '2026-04-30'\n---\n# Daily\n\nrevisited 5 strategy options\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    synth = _stub_synth({
        "themes": [
            {"text": "exploring 5 strategy options", "citations": ["2026-04-29", "2026-04-30"]},
        ],
        "open_loops": [],
        "day_summaries": [
            {"date": "2026-04-29", "summary": "noted 5 strategy options"},
            {"date": "2026-04-30", "summary": "revisited the 5 options"},
        ],
    })
    f = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-30",
        synth=synth,
    )
    assert f.count_check_passed is True
    assert f.count_check_failures == []
    assert f.confidence in ("medium", "high")
    assert any("5 strategy options" in t.text for t in f.themes)


def test_build_fold_count_check_blocks_invented_numbers(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\nshort text\n")
    _write(tmp_path, "z Daily Notes/2026-04-30.md",
           "---\nupdated: '2026-04-30'\n---\n# Daily\n\nshort text\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    synth = _stub_synth({
        "themes": [
            {"text": "user explored 7 ideas", "citations": ["2026-04-29"]},  # 7 not in source
        ],
        "open_loops": [],
        "day_summaries": [],
    })
    f = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-30",
        synth=synth,
    )
    assert f.count_check_passed is False
    assert any("7" in msg for msg in f.count_check_failures)
    assert f.confidence == "low"


def test_count_check_rejects_citations_outside_source_dates(tmp_path):
    """Citations referring to dates that no source has = LLM confabulating
    provenance. Must fail the count-check."""
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\ntext\n")
    _write(tmp_path, "z Daily Notes/2026-04-30.md",
           "---\nupdated: '2026-04-30'\n---\n# Daily\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    synth = _stub_synth({
        "themes": [
            {"text": "real theme", "citations": ["2026-04-29", "2026-05-03"]},
        ],
        "open_loops": [],
        "day_summaries": [
            {"date": "2026-12-25", "summary": "future date — confabulation"},
        ],
    })
    f = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-30",
        synth=synth,
    )
    assert f.count_check_passed is False
    assert any("2026-05-03" in msg for msg in f.count_check_failures)
    assert any("2026-12-25" in msg for msg in f.count_check_failures)


def test_build_fold_handles_synth_failure_gracefully(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    synth = _stub_synth_failure("ollama unreachable: connection refused")
    f = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-30",
        synth=synth,
    )
    assert f.themes == []
    assert f.confidence == "low"
    assert any("ollama unreachable" in msg for msg in f.count_check_failures)
    # Source manifest still populated (cheap, no LLM dep).
    assert any(s.path.endswith("2026-04-29.md") for s in f.sources)


def test_wikilink_heat_counts_cross_day_mentions(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Day1\n\n[[Mechanism Design]] and [[Acme]]\n")
    _write(tmp_path, "z Daily Notes/2026-04-30.md",
           "---\nupdated: '2026-04-30'\n---\n# Day2\n\nback to [[Mechanism Design]]\n")
    _write(tmp_path, "Acme.md", "# Acme\n\nbody\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    f = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-30",
        synth=_stub_synth({"themes": [], "open_loops": [], "day_summaries": []}),
    )
    targets = {h.target: h for h in f.wikilink_heat}
    # Mechanism Design appears on 2 days → in heat (incipient)
    assert "Mechanism Design" in targets
    assert targets["Mechanism Design"].count == 2
    assert targets["Mechanism Design"].resolves is False
    # Acme appears on 1 day, but resolves; depending on count threshold it
    # may not appear. The contract is just that incipient links surface clearly.
    if "Acme" in targets:
        assert targets["Acme"].resolves is True


def test_commit_writes_fold_and_log(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    f = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-29", range_end="2026-04-29",
        synth=_stub_synth({"themes": [], "open_loops": [], "day_summaries": []}),
    )
    target = fold.commit(f, tmp_path)
    assert target.exists()
    body = target.read_text()
    assert f.fold_id in body
    assert "type: fold" in body
    assert "author: '[[gbrain]]'" in body

    log = (tmp_path / fold.FOLD_LOG_REL).read_text()
    assert f.fold_id in log


def test_commit_refuses_existing_without_force(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    f = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-29", range_end="2026-04-29",
        synth=_stub_synth({"themes": [], "open_loops": [], "day_summaries": []}),
    )
    fold.commit(f, tmp_path)

    import pytest
    with pytest.raises(FileExistsError):
        fold.commit(f, tmp_path)

    fold.commit(f, tmp_path, force=True)  # explicit override works


def test_last_committed_fold_end_reads_log(tmp_path):
    log = tmp_path / fold.FOLD_LOG_REL
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "# eno fold log\n\n"
        "- [2026-04-22 12:00:00] **fold-2026-04-15-to-2026-04-22-n6** (...)\n"
        "- [2026-04-29 09:00:00] **fold-2026-04-23-to-2026-04-29-n8** (...)\n"
    )
    last = fold.last_committed_fold_end(tmp_path)
    assert last == "2026-04-29"


def test_last_committed_fold_end_returns_none_when_missing(tmp_path):
    assert fold.last_committed_fold_end(tmp_path) is None


def test_parse_fold_frontmatter_round_trip(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    f = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-29", range_end="2026-04-29",
        synth=_stub_synth({"themes": [], "open_loops": [], "day_summaries": []}),
    )
    target = fold.commit(f, tmp_path)
    parsed = fold.parse_fold_frontmatter(target)
    assert parsed is not None
    assert parsed["range_start"] == "2026-04-29"
    assert parsed["range_end"] == "2026-04-29"
    assert parsed["level"] == "1"  # parser returns strings; CLI converts
    assert "title" in parsed


def test_list_committed_folds_sorts_by_range(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-15.md",
           "---\nupdated: '2026-04-15'\n---\n# A\n\ntext\n")
    _write(tmp_path, "z Daily Notes/2026-04-22.md",
           "---\nupdated: '2026-04-22'\n---\n# B\n\ntext\n")
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# C\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    synth = _stub_synth({"themes": [], "open_loops": [], "day_summaries": []})

    f1 = fold.build_fold(db, tmp_path, range_start="2026-04-22", range_end="2026-04-22", synth=synth)
    f2 = fold.build_fold(db, tmp_path, range_start="2026-04-15", range_end="2026-04-15", synth=synth)
    f3 = fold.build_fold(db, tmp_path, range_start="2026-04-29", range_end="2026-04-29", synth=synth)
    fold.commit(f1, tmp_path)
    fold.commit(f2, tmp_path)
    fold.commit(f3, tmp_path)

    rows = fold.list_committed_folds(tmp_path)
    starts = [r["range_start"] for r in rows]
    assert starts == ["2026-04-15", "2026-04-22", "2026-04-29"]


def test_commit_supersedes_contained_folds(tmp_path):
    """Committing a wider fold auto-supersedes any contained child folds."""
    for d in ("2026-04-25", "2026-04-26", "2026-04-29", "2026-04-30"):
        _write(tmp_path, f"z Daily Notes/{d}.md",
               f"---\nupdated: '{d}'\n---\n# {d}\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    synth = _stub_synth({"themes": [], "open_loops": [], "day_summaries": []})

    # First, commit a narrow fold: 2026-04-25 to 2026-04-26
    inner = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-26",
        synth=synth,
    )
    inner_path = fold.commit(inner, tmp_path)

    # Then a wider one that contains it.
    outer = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-25", range_end="2026-04-30",
        synth=synth,
    )
    outer_path = fold.commit(outer, tmp_path)

    # Outer's frontmatter should list inner under supersedes:
    outer_fm = fold.parse_fold_frontmatter(outer_path)
    assert isinstance(outer_fm.get("supersedes"), list)
    assert any(inner.fold_id in s for s in outer_fm["supersedes"])

    # Inner's frontmatter should now have superseded_by:
    inner_fm = fold.parse_fold_frontmatter(inner_path)
    assert outer.fold_id in (inner_fm.get("superseded_by") or "")
    assert inner_fm.get("superseded_at")


def test_commit_does_not_supersede_overlapping_but_not_contained(tmp_path):
    for d in ("2026-04-22", "2026-04-23", "2026-04-29", "2026-04-30"):
        _write(tmp_path, f"z Daily Notes/{d}.md",
               f"---\nupdated: '{d}'\n---\n# {d}\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    synth = _stub_synth({"themes": [], "open_loops": [], "day_summaries": []})

    # First fold: 2026-04-22 → 2026-04-29 (one week)
    a = fold.build_fold(db, tmp_path, range_start="2026-04-22", range_end="2026-04-29", synth=synth)
    a_path = fold.commit(a, tmp_path)

    # Second fold: 2026-04-25 → 2026-04-30 (overlapping but not contained)
    b = fold.build_fold(db, tmp_path, range_start="2026-04-25", range_end="2026-04-30", synth=synth)
    b_path = fold.commit(b, tmp_path)

    # Neither should have superseded the other (overlap, no containment).
    a_fm = fold.parse_fold_frontmatter(a_path)
    b_fm = fold.parse_fold_frontmatter(b_path)
    assert not a_fm.get("superseded_by")
    assert not b_fm.get("supersedes") or b_fm.get("supersedes") == []


def test_build_fold_over_folds_synthesizes_cross_fold(tmp_path):
    """L2 fold input is the child fold markdowns, output cites child IDs."""
    for d in ("2026-04-15", "2026-04-22", "2026-04-29"):
        _write(tmp_path, f"z Daily Notes/{d}.md",
               f"---\nupdated: '{d}'\n---\n# {d}\n\ntext content\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    synth = _stub_synth({"themes": [], "open_loops": [], "day_summaries": []})

    c1 = fold.build_fold(db, tmp_path, range_start="2026-04-15", range_end="2026-04-15", synth=synth)
    c2 = fold.build_fold(db, tmp_path, range_start="2026-04-22", range_end="2026-04-22", synth=synth)
    c3 = fold.build_fold(db, tmp_path, range_start="2026-04-29", range_end="2026-04-29", synth=synth)
    fold.commit(c1, tmp_path)
    fold.commit(c2, tmp_path)
    fold.commit(c3, tmp_path)
    rows = fold.list_committed_folds(tmp_path)
    children_meta = [r for r in rows if r["fold_id"] in (c1.fold_id, c2.fold_id, c3.fold_id)]

    # L2 synth — the stub returns themes citing actual child IDs.
    l2_synth = _stub_synth({
        "themes": [
            {"text": "recurring concept across folds",
             "citations": [c1.fold_id, c2.fold_id]},
        ],
        "open_loops": [
            {"text": "still pending", "source_date": c3.fold_id},
        ],
        "day_summaries": [
            {"date": c1.fold_id, "summary": "first child summary"},
            {"date": c2.fold_id, "summary": "second child summary"},
        ],
    })
    f = fold.build_fold_over_folds(
        tmp_path,
        children_meta=children_meta,
        range_start="2026-04-15",
        range_end="2026-04-29",
        synth=l2_synth,
    )
    assert f.level == 2
    assert f.children == [c1.fold_id, c2.fold_id, c3.fold_id]
    assert f.fold_id.startswith("fold-L2-")
    assert f.count_check_passed is True
    assert any(c1.fold_id in t.citations for t in f.themes)


def test_build_fold_over_folds_count_check_blocks_unknown_child_id(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-15.md",
           "---\nupdated: '2026-04-15'\n---\n# A\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    c1 = fold.build_fold(
        db, tmp_path, range_start="2026-04-15", range_end="2026-04-15",
        synth=_stub_synth({"themes": [], "open_loops": [], "day_summaries": []}),
    )
    fold.commit(c1, tmp_path)
    rows = fold.list_committed_folds(tmp_path)

    bad_synth = _stub_synth({
        "themes": [
            {"text": "fabricated theme", "citations": ["fold-bogus-fake-n9"]},
        ],
        "open_loops": [],
        "day_summaries": [],
    })
    f = fold.build_fold_over_folds(
        tmp_path,
        children_meta=rows,
        range_start="2026-04-15",
        range_end="2026-04-15",
        synth=bad_synth,
    )
    assert f.count_check_passed is False
    assert any("fold-bogus-fake-n9" in msg for msg in f.count_check_failures)


def test_render_markdown_l2_includes_children_section(tmp_path):
    f = fold.Fold(
        fold_id="fold-L2-2026-04-15-to-2026-04-29-n3",
        range_start="2026-04-15",
        range_end="2026-04-29",
        level=2,
        children=["fold-2026-04-15-to-2026-04-22-n6", "fold-2026-04-23-to-2026-04-29-n8"],
    )
    body = fold.render_markdown(f)
    assert "level: 2" in body
    assert "## Children" in body
    assert "## Sources" not in body
    assert "## Wikilink heat" not in body  # no graph signal at L2


def test_topic_slug_handles_unsafe_chars():
    assert fold.topic_slug("Acme") == "acme"
    assert fold.topic_slug("2 Projects/Acme") == "2-projects-acme"
    assert fold.topic_slug("emoji 🚀 strip") == "emoji-strip"
    assert fold.topic_slug("") == "topic"
    assert fold.topic_slug("---") == "topic"


def test_topic_fold_id_is_deterministic():
    a = fold.topic_fold_id("wikilink", "Acme", 5)
    b = fold.topic_fold_id("wikilink", "Acme", 5)
    c = fold.topic_fold_id("wikilink", "Acme", 6)
    d = fold.topic_fold_id("folder", "Acme", 5)
    assert a == b == "fold-topic-wikilink-acme-n5"
    assert a != c
    assert a != d  # kind matters


def test_topic_sources_wikilink_includes_hub_and_linkers(tmp_path):
    """Hub note + every note linking to [[X]]."""
    _write(tmp_path, "2 Projects/Acme.md", "# Acme\n\nhub note body\n")
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "# Day\n\nthinking about [[Acme]] strategy\n")
    _write(tmp_path, "Patterns/p1.md",
           "# Pattern 1\n\nreference [[Acme]] in design discussion\n")
    _write(tmp_path, "Other.md", "# Other\n\nunrelated content\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    sources = fold.load_topic_sources(db, tmp_path, "wikilink", "Acme")
    paths = {s.path for s in sources}
    assert "2 Projects/Acme.md" in paths      # hub
    assert "z Daily Notes/2026-04-29.md" in paths   # linker
    assert "Patterns/p1.md" in paths                # linker
    assert "Other.md" not in paths                  # not linked
    assert all(s.tier == "topic" for s in sources)


def test_topic_sources_wikilink_falls_back_to_title_match(tmp_path):
    """If no incoming links exist yet, the topic note itself can still
    be found by case-insensitive title match."""
    _write(tmp_path, "Mechanism Design.md",
           "# Mechanism Design\n\nbody " * 30 + "\n")  # >80 word floor for indexer
    index_vault(tmp_path)
    db = _open(tmp_path)
    sources = fold.load_topic_sources(db, tmp_path, "wikilink", "Mechanism Design")
    paths = {s.path for s in sources}
    assert "Mechanism Design.md" in paths


def test_topic_sources_folder_includes_subtree_and_sibling_hub(tmp_path):
    _write(tmp_path, "2 Projects/Acme.md", "# Hub\n\nhub body\n")
    _write(tmp_path, "2 Projects/Acme/Gadget.md", "# Gadget\n\ngadget body\n")
    _write(tmp_path, "2 Projects/Acme/Sprocket.md", "# Sprocket\n\nsprocket body\n")
    _write(tmp_path, "2 Projects/Other.md", "# Other\n\nother project\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    sources = fold.load_topic_sources(db, tmp_path, "folder", "2 Projects/Acme")
    paths = {s.path for s in sources}
    assert "2 Projects/Acme.md" in paths       # sibling hub
    assert "2 Projects/Acme/Gadget.md" in paths  # subtree
    assert "2 Projects/Acme/Sprocket.md" in paths
    assert "2 Projects/Other.md" not in paths        # different project


def test_topic_sources_tag_filters_correctly(tmp_path):
    _write(tmp_path, "A.md", "---\ntags: [acme]\n---\n# A\n\nbody\n")
    _write(tmp_path, "B.md", "---\ntags: [other]\n---\n# B\n\nbody\n")
    _write(tmp_path, "C.md", "---\ntags: [acme, other]\n---\n# C\n\nbody\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    sources = fold.load_topic_sources(db, tmp_path, "tag", "acme")
    paths = {s.path for s in sources}
    assert paths == {"A.md", "C.md"}


def test_topic_sources_tag_is_case_insensitive(tmp_path):
    _write(tmp_path, "A.md", "---\ntags: [Acme]\n---\n# A\n\nbody\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    assert {s.path for s in fold.load_topic_sources(db, tmp_path, "tag", "acme")} == {"A.md"}


def test_topic_sources_unknown_kind_raises(tmp_path):
    index_vault(tmp_path)
    db = _open(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="unknown topic kind"):
        fold.load_topic_sources(db, tmp_path, "bogus", "x")


def test_build_topic_fold_passes_count_check_when_citations_in_stems(tmp_path):
    _write(tmp_path, "Hub.md", "# Hub\n\nbody mentioning a recurring concept\n")
    _write(tmp_path, "A.md", "# A\n\n[[Hub]] discussion: same recurring concept\n")
    _write(tmp_path, "B.md", "# B\n\n[[Hub]] echoed: that recurring concept\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    synth = _stub_synth({
        "themes": [
            {"text": "the recurring concept", "citations": ["A", "B"]},
        ],
        "open_loops": [],
        "day_summaries": [
            {"date": "Hub", "summary": "introduces the concept"},
        ],
    })
    f = fold.build_topic_fold(
        db, tmp_path, kind="wikilink", value="Hub", synth=synth,
    )
    assert f.count_check_passed is True
    assert f.fold_id.startswith("fold-topic-wikilink-hub-")
    assert any("the recurring concept" in t.text for t in f.themes)
    # Range derived from sources
    assert f.range_start
    assert f.range_end


def test_build_topic_fold_count_check_blocks_unknown_stems(tmp_path):
    _write(tmp_path, "A.md", "# A\n\n[[Topic]] body\n")
    _write(tmp_path, "B.md", "# B\n\n[[Topic]] body\n")
    _write(tmp_path, "Topic.md", "# Topic\n\nhub\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    synth = _stub_synth({
        "themes": [
            {"text": "fabricated", "citations": ["Nonexistent Source"]},
        ],
        "open_loops": [],
        "day_summaries": [],
    })
    f = fold.build_topic_fold(
        db, tmp_path, kind="wikilink", value="Topic", synth=synth,
    )
    assert f.count_check_passed is False
    assert any("Nonexistent Source" in msg for msg in f.count_check_failures)


def test_build_topic_fold_no_sources(tmp_path):
    index_vault(tmp_path)
    db = _open(tmp_path)
    f = fold.build_topic_fold(
        db, tmp_path, kind="wikilink", value="Nonexistent",
        synth=_stub_synth({"themes": [], "open_loops": [], "day_summaries": []}),
    )
    assert len(f.sources) == 0
    assert f.confidence == "low"
    assert f.fold_id.endswith("-n0")


def test_topic_fold_render_uses_topic_specific_phrasing(tmp_path):
    f = fold.Fold(
        fold_id="fold-topic-wikilink-acme-n3",
        range_start="2026-04-15",
        range_end="2026-04-29",
        sources=[
            fold.FoldSource(path="A.md", title="A", tier="topic",
                            date="2026-04-15", excerpt=""),
        ],
    )
    body = fold.render_markdown(f)
    assert "Per-source summaries" in body  # not "Per-day TL;DR"
    assert "## Wikilink heat" not in body  # suppressed for topic folds
    assert "related to one topic" in body  # topic-specific summary line
    assert "[topic]" in body                # source tier marker


def test_topic_fold_path_lives_in_topic_subdir(tmp_path):
    f = fold.Fold(
        fold_id="fold-topic-wikilink-acme-n3",
        range_start="2026-04-15",
        range_end="2026-04-29",
    )
    p = fold.fold_path(tmp_path, f.fold_id)
    assert p.parent.name == "topic"
    assert p.parent.parent.name == "folds"


def test_render_markdown_includes_warning_on_failed_count_check(tmp_path):
    _write(tmp_path, "z Daily Notes/2026-04-29.md",
           "---\nupdated: '2026-04-29'\n---\n# Daily\n\ntext\n")
    index_vault(tmp_path)
    db = _open(tmp_path)

    synth = _stub_synth({
        "themes": [{"text": "claims 9 things", "citations": ["2026-04-29"]}],
        "open_loops": [],
        "day_summaries": [],
    })
    f = fold.build_fold(
        db, tmp_path,
        range_start="2026-04-29", range_end="2026-04-29",
        synth=synth,
    )
    body = fold.render_markdown(f)
    assert "[!warning]" in body
    assert "Count check failed" in body
