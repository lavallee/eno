"""Tests for query primitives. Each builds a small fixture vault, indexes it, then queries."""

import time
from pathlib import Path

from eno import queries
from eno.config import index_path
from eno.db import open_index
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


def test_search_by_title(tmp_path):
    _write(tmp_path, "Alpha Beta.md", "# Alpha Beta\n")
    _write(tmp_path, "Gamma.md", "# Gamma\n")
    _write(tmp_path, "Beta Two.md", "# Beta Two\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    hits = queries.search(db, "beta")
    paths = [h.path for h in hits]
    assert "Alpha Beta.md" in paths
    assert "Beta Two.md" in paths
    assert "Gamma.md" not in paths


def test_search_by_tag(tmp_path):
    _write(tmp_path, "A.md", "---\ntags: [foo]\n---\n# A\n")
    _write(tmp_path, "B.md", "---\ntags: [bar]\n---\n# B\n")
    _write(tmp_path, "C.md", "---\ntags: [foo, bar]\n---\n# C\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    hits = queries.search(db, "foo", kind="tag")
    paths = sorted(h.path for h in hits)
    assert paths == ["A.md", "C.md"]


def test_search_unknown_kind_raises(tmp_path):
    _write(tmp_path, "X.md", "# X\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        queries.search(db, "x", kind="bogus")


def test_note_returns_view(tmp_path):
    _write(tmp_path, "X.md", "---\ntype: research\norigin: human\n---\n# X\n\n## Sub\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    view = queries.note(db, "X.md")
    assert view is not None
    assert view.title == "X"
    assert view.frontmatter["type"] == "research"
    assert [(h.level, h.text) for h in view.headings] == [(1, "X"), (2, "Sub")]


def test_note_missing_returns_none(tmp_path):
    _write(tmp_path, "X.md", "# X\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    assert queries.note(db, "Nope.md") is None


def test_neighbors(tmp_path):
    _write(tmp_path, "A.md", "# A\n\n[[B]] [[C]]\n")
    _write(tmp_path, "B.md", "# B\n\nback to [[A]]\n")
    _write(tmp_path, "C.md", "# C\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    n = queries.neighbors(db, "A.md")
    assert n is not None
    backlink_paths = [r.path for r in n.backlinks]
    outbound_paths = [r.path for r in n.outbound]
    assert backlink_paths == ["B.md"]
    assert sorted(outbound_paths) == ["B.md", "C.md"]


def test_orphans_filters_by_folder_and_min_words(tmp_path):
    _write(tmp_path, "research/Big.md", "# Big\n\n" + ("word " * 200))
    _write(tmp_path, "research/Tiny.md", "# Tiny\n")
    _write(tmp_path, "other/Big2.md", "# Big2\n\n" + ("word " * 200))
    _write(tmp_path, "Linker.md", "# Linker\n\n[[Big]]\n")  # links Big, so Big has inbound
    index_vault(tmp_path)
    db = _open(tmp_path)

    rows = queries.orphans(db, folder="research")
    paths = [r.path for r in rows]
    assert "research/Tiny.md" in paths
    assert "research/Big.md" not in paths  # has inbound from Linker
    assert "other/Big2.md" not in paths  # filtered by folder

    rows_big = queries.orphans(db, min_words=100)
    paths_big = [r.path for r in rows_big]
    assert "other/Big2.md" in paths_big
    assert "research/Tiny.md" not in paths_big


def test_stubs_excludes_notes_with_outbound_links(tmp_path):
    _write(tmp_path, "Stub.md", "# Stub\n")
    _write(tmp_path, "ShortLinker.md", "# Short\n\n[[Stub]]\n")
    _write(tmp_path, "Long.md", "# Long\n\n" + ("word " * 200))
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows = queries.stubs(db, max_words=10)
    paths = [r.path for r in rows]
    assert "Stub.md" in paths
    assert "ShortLinker.md" not in paths  # has outbound
    assert "Long.md" not in paths  # too long


def test_stale(tmp_path):
    long_ago = time.time() - 365 * 86400
    recent = time.time() - 5 * 86400
    _write(tmp_path, "Old.md", "# Old\n", mtime=long_ago)
    _write(tmp_path, "Fresh.md", "# Fresh\n", mtime=recent)
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows = queries.stale(db, older_than_days=180)
    paths = [r.path for r in rows]
    assert "Old.md" in paths
    assert "Fresh.md" not in paths


def test_stale_excludes_reference_and_archived_by_default(tmp_path):
    long_ago = time.time() - 365 * 86400
    _write(tmp_path, "Ref.md", "---\nstage: reference\n---\n# Ref\n", mtime=long_ago)
    _write(tmp_path, "Arc.md", "---\nstage: archived\n---\n# Arc\n", mtime=long_ago)
    _write(tmp_path, "Active.md", "---\nstage: active\n---\n# Active\n", mtime=long_ago)
    index_vault(tmp_path)
    db = _open(tmp_path)
    paths = [r.path for r in queries.stale(db, older_than_days=180)]
    assert paths == ["Active.md"]


def test_stale_uses_frontmatter_updated_when_present(tmp_path):
    """Notes with an `updated:` field use that, not mtime — so a fresh
    git clone (recent mtime) doesn't hide an old `updated:` date."""
    recent = time.time() - 5 * 86400  # mtime says recent
    _write(
        tmp_path,
        "OldUpdated.md",
        "---\nupdated: '2024-01-01'\n---\n# Old\n",
        mtime=recent,
    )
    _write(
        tmp_path,
        "RecentUpdated.md",
        "---\nupdated: '2026-04-01'\n---\n# Recent\n",
        mtime=recent,
    )
    _write(tmp_path, "NoUpdated.md", "# No Updated\n", mtime=recent)
    index_vault(tmp_path)
    db = _open(tmp_path)
    paths = [r.path for r in queries.stale(db, older_than_days=180)]
    assert paths == ["OldUpdated.md"]


def test_stale_falls_back_to_mtime_when_updated_absent(tmp_path):
    """When `updated:` is absent, mtime drives staleness as before."""
    long_ago = time.time() - 365 * 86400
    recent = time.time() - 5 * 86400
    _write(tmp_path, "OldNoFm.md", "# Old\n", mtime=long_ago)
    _write(tmp_path, "Fresh.md", "# Fresh\n", mtime=recent)
    index_vault(tmp_path)
    db = _open(tmp_path)
    paths = [r.path for r in queries.stale(db, older_than_days=180)]
    assert paths == ["OldNoFm.md"]


def test_broken_links(tmp_path):
    _write(tmp_path, "A.md", "# A\n\n[[Real]] [[Imaginary]]\n")
    _write(tmp_path, "Real.md", "# Real\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows = queries.broken_links(db)
    targets = [r.target_text for r in rows]
    assert targets == ["Imaginary"]


def test_frontier_orders_by_score(tmp_path):
    """Frontier surfaces high-out, low-in, recent. Hub pages drop, stale drops."""
    recent = time.time() - 1 * 86400
    long_ago = time.time() - 365 * 86400
    # Frontier: 3 outbound, 0 inbound, recent → high score
    _write(
        tmp_path, "Frontier.md",
        "# Frontier\n\n[[A]] [[B]] [[C]]\n", mtime=recent,
    )
    # Hub: 0 outbound, many inbound → negative score
    _write(tmp_path, "A.md", "# A\n", mtime=recent)
    _write(tmp_path, "B.md", "# B\n", mtime=recent)
    _write(tmp_path, "C.md", "# C\n\n[[A]]\n", mtime=recent)
    # Stale frontier: high outbound, no inbound, but old → tiny score
    _write(
        tmp_path, "Forgotten.md",
        "# Forgotten\n\n[[A]] [[B]]\n", mtime=long_ago,
    )
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows = queries.frontier(db)
    paths = [r.path for r in rows]
    assert paths[0] == "Frontier.md"
    by_path = {r.path: r for r in rows}
    # Stale page is positive-but-tiny; ranks far below recent frontier.
    assert by_path["Forgotten.md"].score < by_path["Frontier.md"].score / 100
    assert "A.md" not in paths  # in_degree=2, out=0 → negative, filtered
    assert "B.md" not in paths  # in_degree=1, out=0 → negative, filtered


def test_frontier_recency_decay(tmp_path):
    """Same out/in, different age → newer wins."""
    new = time.time() - 1 * 86400
    old = time.time() - 60 * 86400  # 2 halflives
    _write(tmp_path, "New.md", "# New\n\n[[X]]\n", mtime=new)
    _write(tmp_path, "Old.md", "# Old\n\n[[X]]\n", mtime=old)
    _write(tmp_path, "X.md", "# X\n", mtime=new)
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows = queries.frontier(db, halflife_days=30.0)
    by_path = {r.path: r for r in rows}
    assert by_path["New.md"].score > by_path["Old.md"].score
    # Old at age=60, halflife=30: weight = exp(-2) ≈ 0.135
    assert 0.10 < by_path["Old.md"].recency_weight < 0.16


def test_frontier_folder_filter(tmp_path):
    recent = time.time() - 1 * 86400
    _write(tmp_path, "research/Hot.md", "# Hot\n\n[[X]] [[Y]]\n", mtime=recent)
    _write(tmp_path, "other/Hot2.md", "# Hot2\n\n[[X]] [[Y]]\n", mtime=recent)
    _write(tmp_path, "X.md", "# X\n", mtime=recent)
    _write(tmp_path, "Y.md", "# Y\n", mtime=recent)
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows = queries.frontier(db, folder="research")
    paths = [r.path for r in rows]
    assert paths == ["research/Hot.md"]


def test_frontier_excludes_by_type(tmp_path):
    recent = time.time() - 1 * 86400
    _write(
        tmp_path, "Log.md",
        "---\ntype: log\n---\n# Log\n\n[[A]] [[B]]\n", mtime=recent,
    )
    _write(
        tmp_path, "Note.md",
        "---\ntype: research\n---\n# Note\n\n[[A]] [[B]]\n", mtime=recent,
    )
    _write(tmp_path, "A.md", "# A\n", mtime=recent)
    _write(tmp_path, "B.md", "# B\n", mtime=recent)
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows = queries.frontier(db, exclude_types=["log"])
    paths = [r.path for r in rows]
    assert "Log.md" not in paths
    assert "Note.md" in paths


def test_frontier_include_nonpositive(tmp_path):
    """include_nonpositive=True surfaces hubs (negative) and zero-score pages."""
    recent = time.time() - 1 * 86400
    _write(tmp_path, "Hub.md", "# Hub\n", mtime=recent)
    _write(tmp_path, "Linker1.md", "# L1\n\n[[Hub]]\n", mtime=recent)
    _write(tmp_path, "Linker2.md", "# L2\n\n[[Hub]]\n", mtime=recent)
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows_default = queries.frontier(db)
    assert "Hub.md" not in [r.path for r in rows_default]
    rows_all = queries.frontier(db, include_nonpositive=True)
    by_path = {r.path: r for r in rows_all}
    assert by_path["Hub.md"].score < 0
    assert by_path["Hub.md"].in_degree == 2
    assert by_path["Hub.md"].out_degree == 0


def test_recent_appends_within_window(tmp_path):
    recent = time.time() - 1 * 86400
    older = time.time() - 30 * 86400
    _write(tmp_path, "Fresh.md", "# Fresh\n", mtime=recent)
    _write(tmp_path, "Old.md", "# Old\n", mtime=older)
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows = queries.recent_appends(db, within_days=7)
    paths = [r.path for r in rows]
    assert paths == ["Fresh.md"]


def test_agent_recent_filters_by_author(tmp_path):
    recent = time.time() - 1 * 86400
    _write(
        tmp_path, "ByWeaver.md",
        "---\nauthor: '[[Weaver]]'\n---\n# By Weaver\n", mtime=recent,
    )
    _write(
        tmp_path, "ByUser.md",
        "---\nauthor: '[[the user]]'\n---\n# By the user\n", mtime=recent,
    )
    _write(tmp_path, "Anon.md", "# Anonymous\n", mtime=recent)
    index_vault(tmp_path)
    db = _open(tmp_path)
    rows = queries.agent_recent(db, agent_name="Weaver")
    paths = [r.path for r in rows]
    assert paths == ["ByWeaver.md"]


def test_agent_recent_empty_name_returns_empty(tmp_path):
    _write(tmp_path, "X.md", "---\nauthor: '[[Whoever]]'\n---\n# X\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    assert queries.agent_recent(db, agent_name="") == []


def test_hot_aggregates_signals(tmp_path):
    """Hot bundle pulls from frontier + recent_appends + concepts + agent."""
    recent = time.time() - 1 * 86400
    # Frontier-shaped page
    _write(
        tmp_path, "Frontier.md",
        "# Frontier\n\n[[A]] [[B]] [[C]]\n", mtime=recent,
    )
    _write(tmp_path, "A.md", "# A\n", mtime=recent)
    _write(tmp_path, "B.md", "# B\n", mtime=recent)
    _write(tmp_path, "C.md", "# C\n", mtime=recent)
    # Concept candidate (incipient wikilink, target doesn't exist)
    _write(
        tmp_path, "Mentions.md",
        "# Mentions\n\nthinking about [[Mechanism Design]] again\n",
        mtime=recent,
    )
    # Weaver-authored note
    _write(
        tmp_path, "Synthesis.md",
        "---\nauthor: '[[Weaver]]'\n---\n# Synthesis\n", mtime=recent,
    )
    index_vault(tmp_path)
    db = _open(tmp_path)
    bundle = queries.hot(db, agent_name="Weaver")
    assert bundle.agent_name == "Weaver"
    assert bundle.generated_at  # ISO timestamp present
    frontier_paths = [f.path for f in bundle.frontier]
    assert "Frontier.md" in frontier_paths
    recent_paths = [r.path for r in bundle.recent_appends]
    assert "Mentions.md" in recent_paths
    concept_targets = [c.target_text for c in bundle.top_concepts]
    assert "Mechanism Design" in concept_targets
    agent_paths = [r.path for r in bundle.agent_recent]
    assert agent_paths == ["Synthesis.md"]


def test_note_view_carries_flip_fields(flip_vault):
    index_vault(flip_vault)
    db = _open(flip_vault)
    view = queries.note(db, "research/hosm/claims/claim-one.md")
    assert view is not None
    assert view.flip_id == "C1"
    assert view.bundle_path == "research/hosm"
    assert view.bundle_handle == "hosm"


def test_note_view_flip_fields_none_on_plain_vault(tmp_path):
    # X.md carries `id: Q4` frontmatter — but flip_id is only meaningful inside
    # a bundle, so on a flip-free vault the note view must still return None.
    _write(tmp_path, "X.md", "---\nid: Q4\n---\n# X\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    view = queries.note(db, "X.md")
    assert view is not None
    assert view.flip_id is None
    assert view.bundle_path is None
    assert view.bundle_handle is None


def test_hot_top_concepts_exclude_flip_refs(flip_vault):
    _write(flip_vault, "Ideas.md", "# Ideas\n\n[[Mechanism Design]]\n")
    index_vault(flip_vault)
    db = _open(flip_vault)
    bundle = queries.hot(db)
    targets = [c.target_text for c in bundle.top_concepts]
    assert "Mechanism Design" in targets
    # Id-shaped flip refs from the fixture never pollute top_concepts.
    assert "A33" not in targets
    assert "nope:A1" not in targets


def test_hot_top_concepts_keep_id_shaped_on_flip_free_vault(tmp_path):
    """On a flip-free vault, [[Q4]] is an ordinary concept even when some note
    carries `id: Q4` frontmatter — hot's top_concepts must include it, exactly
    as if the frontmatter weren't there."""
    _write(tmp_path, "Quarter.md", "---\nid: Q4\n---\n# Quarter\n")
    _write(tmp_path, "Other.md", "# Other\n\n[[Q4]]\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    bundle = queries.hot(db)
    assert "Q4" in [c.target_text for c in bundle.top_concepts]


def test_hygiene(tmp_path):
    _write(tmp_path, "Full.md", "---\norigin: human\nstage: active\n---\n# Full\n")
    _write(tmp_path, "Half.md", "---\norigin: llm\n---\n# Half\n")
    _write(tmp_path, "Empty.md", "# Empty\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    rep = queries.hygiene(db)
    assert rep.counts["total"] == 3
    assert rep.counts["origin"] == 1  # only Empty.md
    assert rep.counts["stage"] == 2  # Half + Empty
    by_path = {i.path: i for i in rep.issues}
    assert "Full.md" not in by_path
    assert by_path["Half.md"].missing == ["stage"]
    assert sorted(by_path["Empty.md"].missing) == ["origin", "stage"]
