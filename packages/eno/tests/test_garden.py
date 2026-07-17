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


# ---- flip refs -------------------------------------------------------------


def test_id_shaped_broken_link_never_concept_on_flip_vault(flip_vault: Path):
    index_vault(flip_vault)
    rep = garden(_open(flip_vault))
    flip_targets = [f.target_text for f in rep.flip_refs]
    concept_targets = [c.target_text for c in rep.concepts]
    assert "nope:A1" in flip_targets
    assert "A33" in flip_targets
    # front:T9 fuzzy-matches the front:T2 id tuple (~0.86 ≥ 0.85): drift wins,
    # per the drift-check-first rule. Either way, no id-shaped ref is a concept.
    assert "front:T9" in [d.target_text for d in rep.drift]
    from eno.flip_conventions import REF_SHAPE_RE
    assert not any(REF_SHAPE_RE.match(t) for t in concept_targets)


def test_id_shaped_link_stays_concept_on_flip_free_vault(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n\n[[Q4]] [[H2]]\n")
    index_vault(tmp_path)
    rep = garden(_open(tmp_path))
    assert rep.flip_refs == []
    concept_targets = [c.target_text for c in rep.concepts]
    assert "Q4" in concept_targets
    assert "H2" in concept_targets


def test_unknown_handle_flip_ref_hint(flip_vault: Path):
    index_vault(flip_vault)
    rep = garden(_open(flip_vault))
    by_target = {f.target_text: f for f in rep.flip_refs}
    assert "nope:A1" in by_target
    assert "handle 'nope' is not bound to an indexed bundle" in by_target["nope:A1"].hint
    # Bare ids get the bundle-scoping hint.
    assert "bare ids only resolve" in by_target["A33"].hint


def test_known_handle_unknown_id_hint(flip_vault: Path):
    # Q9 doesn't fuzzy-match any indexed id, so it lands in flip_refs (front:T9
    # from the fixture would drift-match front:T2 instead).
    _write(flip_vault, "Elsewhere.md", "# Elsewhere\n\n[[front:Q9]]\n")
    index_vault(flip_vault)
    rep = garden(_open(flip_vault))
    by_target = {f.target_text: f for f in rep.flip_refs}
    assert by_target["front:Q9"].hint == "no entity Q9 indexed in bundle 'front'"


def test_bare_id_outside_bundle_exact_matches_entity_as_drift(flip_vault: Path):
    # T2 has no alias, so [[T2]] outside any bundle is broken at index time —
    # but it exact-matches the entity id, so garden flags it as 1.0 drift.
    _write(flip_vault, "Outside.md", "# Outside\n\n[[T2]]\n")
    index_vault(flip_vault)
    rep = garden(_open(flip_vault))
    by_target = {d.target_text: d for d in rep.drift}
    assert "T2" in by_target
    assert by_target["T2"].score == 1.0
    assert by_target["T2"].suggested_path == "areas/frontier/threads/thread-two.md"


def test_flip_refs_section_rendered_only_when_nonempty(flip_vault: Path):
    index_vault(flip_vault)
    rep = garden(_open(flip_vault))
    out = render_garden_report(rep)
    assert "## Unresolved flip entity references" in out
    assert "flip_refs:" in out  # counts entry in frontmatter
    assert "[[nope:A1]]" in out


def test_garden_report_byte_identical_on_flip_free_vault(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n\n[[Some Concept]]\n")
    _write(tmp_path, "Y.md", "# Y\n")
    index_vault(tmp_path)
    rep = garden(_open(tmp_path))
    assert rep.flip_refs == []
    out = render_garden_report(rep)
    # No flip section, no flip counts key — the written report matches v1 output.
    assert "flip" not in out.lower()


def test_bare_id_unresolved_in_bundle_shows_flip_ref_hint(flip_vault: Path):
    """An in-bundle bare id that resolves nowhere surfaces in flip_refs with
    the bundle-scoping hint (companion to the finding-2 resolver rule)."""
    _write(flip_vault, "research/hosm/notes/gap.md", "# Gap\n\n[[Q7]]\n")
    index_vault(flip_vault)
    rep = garden(_open(flip_vault))
    by_target = {f.target_text: f for f in rep.flip_refs}
    assert "Q7" in by_target
    assert "bare ids only resolve" in by_target["Q7"].hint


def test_bare_id_cross_bundle_shows_as_exact_drift(flip_vault: Path):
    """In-bundle [[A1]] where the bundle lacks A1 stays unresolved at index
    time (never a cross-bundle guess); garden then flags it as a 1.0 drift
    against an existing A1 entity — drift-check-first, same rule as
    outside-bundle exact matches."""
    _write(
        flip_vault,
        "projects/solo/index.md",
        '---\nokf_version: "0.4"\nflip: "0.4"\n---\n# Solo\n',
    )
    _write(flip_vault, "projects/solo/note.md", "# Note\n\n[[A1]]\n")
    index_vault(flip_vault)
    rep = garden(_open(flip_vault))
    by_target = {d.target_text: d for d in rep.drift}
    assert "A1" in by_target
    assert by_target["A1"].score == 1.0
    assert by_target["A1"].suggested_path in {
        "research/hosm/references/paper-alpha.md",
        "areas/frontier/references/paper-beta.md",
    }


def test_flip_free_vault_id_frontmatter_classified_identically(tmp_path: Path):
    """`id: Q4` frontmatter on a flip-free vault must not change broken-link
    classification or the rendered report vs the same vault without it: [[Q4]]
    stays an ordinary concept candidate (never drift against the id, never a
    flip ref)."""
    va = tmp_path / "with-id"
    vb = tmp_path / "without-id"
    for vault, quarter in (
        (va, "---\nid: Q4\n---\n# Quarter\n"),
        (vb, "# Quarter\n"),
    ):
        _write(vault, "Quarter.md", quarter)
        _write(vault, "Other.md", "# Other\n\n[[Q4]]\n")
        index_vault(vault)
    rep_a = garden(_open(va))
    rep_b = garden(_open(vb))
    assert [c.target_text for c in rep_a.concepts] == ["Q4"]
    assert rep_a.flip_refs == [] == rep_b.flip_refs
    assert rep_a.drift == [] == rep_b.drift
    # Written reports identical modulo timestamps.
    rep_a.generated_at = rep_b.generated_at = "TEST"
    rep_a.stats["elapsed_s"] = rep_b.stats["elapsed_s"] = 0
    assert render_garden_report(rep_a) == render_garden_report(rep_b)


def test_mixed_anchor_group_stays_concept_flip_shaped_row_last(flip_vault: Path):
    """All-rows rule: a group is flip-shaped only when EVERY row is — a mixed
    group ([[ghost#Section One]] + [[ghost#A3]]) stays a concept candidate."""
    _write(flip_vault, "Mix.md", "# Mix\n\n[[ghost#Section One]]\n\n[[ghost#A3]]\n")
    index_vault(flip_vault)
    rep = garden(_open(flip_vault))
    assert "ghost" in [c.target_text for c in rep.concepts]
    assert not any(f.target_text.startswith("ghost") for f in rep.flip_refs)
    assert not any(d.target_text.startswith("ghost") for d in rep.drift)


def test_mixed_anchor_group_stays_concept_flip_shaped_row_first(flip_vault: Path):
    """Same as above with row order reversed — classification must not depend
    on which anchor is seen first."""
    _write(flip_vault, "Mix.md", "# Mix\n\n[[ghost#A3]]\n\n[[ghost#Section One]]\n")
    index_vault(flip_vault)
    rep = garden(_open(flip_vault))
    assert "ghost" in [c.target_text for c in rep.concepts]
    assert not any(f.target_text.startswith("ghost") for f in rep.flip_refs)
    assert not any(d.target_text.startswith("ghost") for d in rep.drift)


def test_all_flip_anchor_group_display_deterministic_both_orders(tmp_path: Path):
    """A group whose rows are ALL flip-shaped but carry different anchors
    ([[ghost#A3]] + [[ghost#T2]]) routes to flip_refs with the sorted-first
    display form, independent of row order."""
    for name, body in (
        ("a", "# One\n\n[[ghost#A3]]\n\n[[ghost#T2]]\n"),
        ("b", "# One\n\n[[ghost#T2]]\n\n[[ghost#A3]]\n"),
    ):
        vault = tmp_path / name
        _write(vault, "nb/index.md", '---\nokf_version: "0.4"\nflip: "0.4"\n---\n# NB\n')
        _write(vault, "One.md", body)
        index_vault(vault)
        rep = garden(_open(vault))
        flip_targets = [f.target_text for f in rep.flip_refs]
        assert "ghost#A3" in flip_targets
        assert "ghost#T2" not in flip_targets
        assert not any(c.target_text == "ghost" for c in rep.concepts)
