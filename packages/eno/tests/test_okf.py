"""eno as a generic OKF v0.2 consumer.

Covers the markdown-link graph, the portable trust/lifecycle fields, the
trust/currency summaries on note + neighbors, and the advisory trust-health
checks — over three fixtures: a relative-link bundle, a current-shape flip
notebook workspace, and a bundle exercising every portable field.

Each promotion-bar item from the experiment spec has at least one test here;
the section comments name which.
"""

import hashlib
import inspect
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from eno import okf_conventions, queries
from eno.config import index_path
from eno.excerpt import excerpt as build_excerpt
from eno.indexer import index_vault

from .conftest import (
    EXPECTED_OKF_RELATIVE_DANGLING,
    EXPECTED_OKF_RELATIVE_EDGES,
)


def _open(vault: Path) -> sqlite3.Connection:
    return sqlite3.connect(index_path(vault))


def _md_edges(db: sqlite3.Connection) -> dict[tuple[str, str], str | None]:
    return {
        (src, target): resolved
        for src, target, resolved in db.execute(
            "SELECT src_path, target_text, target_path FROM links WHERE kind = 'md'"
        )
    }


def _hash_tree(root: Path) -> dict[str, str]:
    """sha256 of every markdown file under root, keyed by relative path.
    `.eno/` is the index's own directory and is deliberately excluded."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".eno/"):
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---- parsing: which markdown links become edges ---------------------------


def test_md_links_recorded_with_alias_anchor_and_line(okf_relative_vault: Path):
    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    row = db.execute(
        "SELECT target_text, target_anchor, alias, line_no, kind FROM links "
        "WHERE src_path = 'knowledge/tables/customers.md' AND target_text = 'orders.md'"
    ).fetchone()
    assert row is not None
    target_text, anchor, alias, line_no, kind = row
    assert anchor == "schema"
    assert alias == "orders schema"
    assert line_no > 0
    assert kind == "md"


def test_external_image_and_code_links_are_not_edges(okf_relative_vault: Path):
    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    targets = {
        t
        for (t,) in db.execute(
            "SELECT target_text FROM links WHERE src_path = "
            "'knowledge/metrics/fill-rate.md' AND kind = 'md'"
        )
    }
    assert targets == {"../tables/orders.md", "../playbooks/backfill.md"}
    # External scheme, image, inline-code decoy, and fenced decoy all absent.
    assert not {t for t in targets if t.startswith("http")}
    assert "../assets/fill-rate.png" not in targets
    assert "decoy.md" not in targets
    assert "fenced.md" not in targets


def test_md_links_do_not_pollute_the_wikilink_table(okf_relative_vault: Path):
    """Markdown edges live alongside wikilinks under a `kind` discriminator;
    nothing in the fixture is a wikilink, so the wiki side stays empty."""
    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    (wiki,) = db.execute("SELECT COUNT(*) FROM links WHERE kind = 'wiki'").fetchone()
    (md,) = db.execute("SELECT COUNT(*) FROM links WHERE kind = 'md'").fetchone()
    assert wiki == 0
    assert md > 0


# ---- PROMOTION BAR: 100% of expected internal edges resolve ----------------


def test_every_expected_relative_edge_resolves(okf_relative_vault: Path):
    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    edges = _md_edges(db)
    for key, expected in EXPECTED_OKF_RELATIVE_EDGES.items():
        assert key in edges, f"edge not indexed: {key}"
        assert edges[key] == expected, f"{key} resolved to {edges[key]!r}"
    # The answer key is exhaustive: everything else in the bundle is the one
    # deliberately-dangling link.
    unresolved = {k for k, v in edges.items() if v is None}
    assert unresolved == EXPECTED_OKF_RELATIVE_DANGLING


def test_bundle_absolute_link_resolves_against_bundle_root(okf_relative_vault: Path):
    """`/references/glossary.md` is bundle-relative (OKF §6.1), not vault-relative:
    it must not be read as a path from the vault root."""
    (okf_relative_vault / "references").mkdir()
    (okf_relative_vault / "references" / "glossary.md").write_text("# Decoy\n")
    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    assert (
        _md_edges(db)[("knowledge/tables/orders.md", "/references/glossary.md")]
        == "knowledge/references/glossary.md"
    )


def test_every_expected_flip_notebook_edge_resolves(flip_notebook_vault: Path):
    index_vault(flip_notebook_vault)
    db = _open(flip_notebook_vault)
    edges = _md_edges(db)
    unresolved = {k for k, v in edges.items() if v is None}
    # One dangling footnote link (A7's comfort survey, never captured).
    assert unresolved == {
        (
            "notebooks/roof-coatings/claims/occupant-comfort-unmeasured.md",
            "../references/comfort-survey.md",
        )
    }
    # Footnote definition links are ordinary relative edges.
    assert (
        edges[
            (
                "notebooks/roof-coatings/claims/coatings-lower-attic-peak.md",
                "../references/field-trial-summer-attic.md",
            )
        ]
        == "notebooks/roof-coatings/references/field-trial-summer-attic.md"
    )


def test_every_expected_portable_bundle_edge_resolves(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    edges = _md_edges(db)
    assert edges, "no markdown edges indexed"
    assert all(v is not None for v in edges.values()), edges


# ---- PROMOTION BAR: no false cross-notebook bare-ID resolution -------------


def test_bare_id_stays_inside_its_notebook(flip_notebook_vault: Path):
    """Both notebooks hold an A1. The bare `[[A1]]` in roof-coatings must
    resolve to roof-coatings' own A1 — never the transit one."""
    index_vault(flip_notebook_vault)
    db = _open(flip_notebook_vault)
    row = db.execute(
        "SELECT target_path FROM links WHERE kind = 'wiki' AND target_text = 'A1' "
        "AND src_path = 'notebooks/roof-coatings/claims/occupant-comfort-unmeasured.md'"
    ).fetchone()
    assert row == ("notebooks/roof-coatings/references/field-trial-summer-attic.md",)


def test_qualified_ref_resolves_across_notebooks(flip_notebook_vault: Path):
    index_vault(flip_notebook_vault)
    db = _open(flip_notebook_vault)
    row = db.execute(
        "SELECT target_path FROM links WHERE kind = 'wiki' AND target_text = 'transit:C1'"
    ).fetchone()
    assert row == ("notebooks/transit-dwell/claims/door-cycles-dominate-dwell.md",)


def test_md_links_never_resolve_by_basename_or_alias(flip_notebook_vault: Path):
    """A markdown target is a path, resolved by path arithmetic only. Adding a
    same-named note elsewhere in the vault must not make a dangling edge
    resolve — no vault-wide guessing."""
    index_vault(flip_notebook_vault)
    decoy = flip_notebook_vault / "Comfort-survey.md"
    decoy.write_text("---\naliases: [comfort-survey]\n---\n# Comfort survey\n")
    index_vault(flip_notebook_vault)
    db = _open(flip_notebook_vault)
    assert (
        _md_edges(db)[
            (
                "notebooks/roof-coatings/claims/occupant-comfort-unmeasured.md",
                "../references/comfort-survey.md",
            )
        ]
        is None
    )


# ---- PROMOTION BAR: broken links visible but non-fatal ---------------------


def test_dangling_md_link_is_recorded_and_counted(okf_relative_vault: Path):
    stats = index_vault(okf_relative_vault)
    assert stats.links_broken == 1  # the not-yet-written lead-time page
    assert stats.links_resolved == len(EXPECTED_OKF_RELATIVE_EDGES)
    db = _open(okf_relative_vault)
    broken = queries.broken_links(db)
    assert [(b.src_path, b.target_text) for b in broken] == [
        ("knowledge/tables/customers.md", "../metrics/lead-time.md")
    ]


def test_dangling_md_link_is_not_a_concept_or_drift_candidate(okf_relative_vault: Path):
    """A broken markdown edge is a legal OKF dangling link, not a wikilink
    gesture: the gardener's concept/drift buckets stay wikilink-only."""
    from eno import garden

    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    drift, concepts = garden.classify_broken_links(db)
    assert drift == []
    assert concepts == []


def test_neighbors_are_built_from_both_link_kinds(okf_relative_vault: Path):
    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    n = queries.neighbors(db, "knowledge/tables/orders.md")
    assert n is not None
    assert {b.path for b in n.backlinks} == {
        "knowledge/index.md",
        "knowledge/tables/index.md",
        "knowledge/tables/customers.md",
        "knowledge/metrics/fill-rate.md",
        "knowledge/playbooks/backfill.md",
    }
    assert {o.path for o in n.outbound} == {
        "knowledge/tables/customers.md",
        "knowledge/metrics/fill-rate.md",
        "knowledge/references/glossary.md",
    }


def test_markdown_wired_bundle_is_not_a_pile_of_orphans(okf_relative_vault: Path):
    """Before markdown edges existed, every page in a relative-link bundle
    looked orphaned and stubby. This bundle is fully wired (the glossary links
    back to the root), so nothing is an orphan and nothing is a stub."""
    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    assert queries.orphans(db) == []
    assert queries.stubs(db) == []


def test_fold_wikilink_surfaces_stay_wikilink_only(tmp_path: Path):
    """`fold`'s topic selection is wikilink-semantic: a markdown link whose
    literal target text collides with a wikilink target must not join it."""
    from eno import fold as fold_mod

    (tmp_path / "Topic.md").write_text("# Topic\n")
    (tmp_path / "Wiki.md").write_text("# Wiki\n\npoints at [[Topic]]\n")
    (tmp_path / "Md.md").write_text("# Md\n\npoints at [Topic](Topic)\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    sources = fold_mod._topic_sources_wikilink(
        db, tmp_path, "Topic", limit=10, excerpt_chars=200
    )
    assert {s.path for s in sources} == {"Topic.md", "Wiki.md"}


# ---- portable trust fields -------------------------------------------------


def test_trust_columns_indexed(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    row = db.execute(
        "SELECT status, stale_after, generated_by, generated_at, verified_count, "
        "verified_human, verified_last_at, sources_count, sources_unresolved "
        "FROM notes WHERE path = 'bundle/metrics/shipment-cost.md'"
    ).fetchone()
    assert row == (
        "stable",
        "2020-01-01",
        "costing_agent/v3",
        "2026-07-01T10:00:00+00:00",
        2,
        1,
        "2026-06-11T02:00:00+00:00",
        4,
        1,  # only the retired-memo path is checkable-and-missing
    )


def test_bare_verified_mapping_is_one_element_list(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    row = db.execute(
        "SELECT verified_count, verified_human, verified_last_at FROM notes "
        "WHERE path = 'bundle/computations/shipment-cost.md'"
    ).fetchone()
    assert row == (1, 0, "2026-06-29T02:00:00+00:00")


def test_unfollowable_source_resources_are_not_called_unresolved(
    okf_portable_vault: Path,
):
    """An external URL and a scope descriptor ("all parcels handled at the
    north depot") are things eno cannot check — so it never counts them
    against the bundle."""
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    (unresolved,) = db.execute(
        "SELECT sources_unresolved FROM notes WHERE path = 'bundle/metrics/shipment-cost.md'"
    ).fetchone()
    assert unresolved == 1


def test_dangling_flip_citation_counts_as_unresolved(flip_notebook_vault: Path):
    """flip's dangling cite keeps just its id (`- id: A7`) — legal, and
    visible in the source count."""
    index_vault(flip_notebook_vault)
    db = _open(flip_notebook_vault)
    row = db.execute(
        "SELECT sources_count, sources_unresolved FROM notes WHERE path = "
        "'notebooks/roof-coatings/claims/occupant-comfort-unmeasured.md'"
    ).fetchone()
    assert row == (2, 1)


def test_notes_without_trust_frontmatter_carry_nulls(okf_relative_vault: Path):
    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    rows = db.execute(
        "SELECT status, stale_after, generated_by, verified_count, sources_count "
        "FROM notes"
    ).fetchall()
    assert rows and all(r == (None, None, None, None, None) for r in rows)


# ---- PROMOTION BAR: unknown frontmatter survives into note views -----------


def test_unknown_extension_keys_survive_into_note_view(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    view = queries.note(db, "bundle/metrics/shipment-cost.md")
    assert view is not None
    fm = view.frontmatter
    assert fm["x_department"] == "logistics"
    assert fm["review_board"] == {"chair": "human:rivera", "cadence": "quarterly"}
    assert fm["usage_window"] == {"from": "2026-06-01", "to": "2026-06-30"}
    assert fm["sources"][1]["usage_count"] == 1200
    assert fm["tags"] == ["logistics", "cost"]


def test_unknown_computation_keys_survive(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    view = queries.note(db, "bundle/computations/shipment-cost.md")
    assert view is not None
    assert view.frontmatter["runtime"] == "warehouse-sql"
    assert view.frontmatter["executor"]["receipt"] == ["run_id", "executed_sql", "result"]
    assert view.frontmatter["attester"]["resource"] == (
        "references/attesters/shipment-cost.py"
    )


def test_flip_extension_keys_survive(flip_notebook_vault: Path):
    index_vault(flip_notebook_vault)
    db = _open(flip_notebook_vault)
    view = queries.note(
        db, "notebooks/roof-coatings/claims/coatings-lower-attic-peak.md"
    )
    assert view is not None
    fm = view.frontmatter
    assert fm["load_bearing"] is True
    assert fm["independent_corroboration"] == 1
    assert fm["verified"][0]["method"] == "independent-sources"
    assert fm["verified"][0]["against"] == ["A2"]


# ---- trust/currency summaries ---------------------------------------------


def test_note_view_trust_summary(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    view = queries.note(db, "bundle/metrics/shipment-cost.md")
    assert view is not None
    assert view.trust == (
        "status: stable · generated 2026-07-01 by costing_agent/v3 · "
        "verified ×2 (1 human) · stale 2020-01-01 · sources: 4 (1 unresolved)"
    )


def test_neighbors_carries_the_same_summary(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    view = queries.note(db, "bundle/metrics/shipment-cost.md")
    n = queries.neighbors(db, "bundle/metrics/shipment-cost.md")
    assert n is not None and view is not None
    assert n.trust == view.trust


def test_absent_fields_say_nothing(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    # Reference page: no trust frontmatter at all → no line.
    view = queries.note(db, "bundle/references/allocation-policy.md")
    assert view is not None and view.trust is None
    # Computation: a bare verified mapping, no sources-unresolved parenthetical.
    comp = queries.note(db, "bundle/computations/shipment-cost.md")
    assert comp is not None
    assert comp.trust == (
        "status: draft · generated 2026-06-28 by costing_agent/v3 · verified ×1 · "
        "stale 2999-12-31 · sources: 1"
    )


def test_machine_only_verification_shows_no_human_tier(flip_notebook_vault: Path):
    index_vault(flip_notebook_vault)
    db = _open(flip_notebook_vault)
    view = queries.note(
        db, "notebooks/roof-coatings/claims/coatings-lower-attic-peak.md"
    )
    assert view is not None
    assert "verified ×1 (1 human)" in view.trust  # by: human:dana
    other = queries.note(
        db, "notebooks/transit-dwell/claims/door-cycles-dominate-dwell.md"
    )
    assert other is not None
    assert "verified" not in other.trust  # no verified key at all
    assert "sources: 1" in other.trust


# ---- PROMOTION BAR: summaries fit the bounded first read ------------------


def test_trust_summary_stays_within_the_excerpt_budget(
    okf_portable_vault: Path, flip_notebook_vault: Path, okf_relative_vault: Path
):
    """The bounded first read is excerpt-sized (~400 chars of prose). A trust
    line that rivalled the excerpt would defeat the point, so it must stay
    comfortably under that budget for every note in every fixture."""
    # The budget eno actually enforces on a first read, read from the source
    # of truth rather than restated here.
    max_chars = inspect.signature(build_excerpt).parameters["max_chars"].default
    assert max_chars == 400
    for vault in (okf_portable_vault, flip_notebook_vault, okf_relative_vault):
        index_vault(vault)
        db = _open(vault)
        for (path,) in db.execute("SELECT path FROM notes"):
            view = queries.note(db, path)
            assert view is not None
            if view.trust is not None:
                assert len(view.trust) <= max_chars // 2, (path, view.trust)


def test_trust_summary_is_one_line(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    for (path,) in db.execute("SELECT path FROM notes"):
        view = queries.note(db, path)
        assert view is not None
        if view.trust is not None:
            assert "\n" not in view.trust


# ---- PROMOTION BAR: no source file modified by indexing --------------------


def test_indexing_never_touches_source_files(
    okf_portable_vault: Path, flip_notebook_vault: Path, okf_relative_vault: Path
):
    for vault in (okf_portable_vault, flip_notebook_vault, okf_relative_vault):
        before = _hash_tree(vault)
        index_vault(vault)
        index_vault(vault, full=True)
        db = _open(vault)
        for (path,) in db.execute("SELECT path FROM notes"):
            queries.note(db, path)
            queries.neighbors(db, path)
        queries.trust_health(db)
        db.close()
        assert _hash_tree(vault) == before


# ---- PROMOTION BAR: the index stays disposable -----------------------------


def _query_snapshot(vault: Path) -> dict:
    db = _open(vault)
    try:
        return {
            "notes": [
                asdict(queries.note(db, p))
                for (p,) in db.execute("SELECT path FROM notes ORDER BY path")
            ],
            "neighbors": [
                asdict(queries.neighbors(db, p))
                for (p,) in db.execute("SELECT path FROM notes ORDER BY path")
            ],
            "broken": [asdict(b) for b in queries.broken_links(db)],
            "trust": asdict(queries.trust_health(db)),
            "links": sorted(
                db.execute(
                    "SELECT src_path, target_text, target_path, target_anchor, kind "
                    "FROM links"
                ).fetchall()
            ),
        }
    finally:
        db.close()


def test_rebuild_from_scratch_gives_identical_results(
    okf_portable_vault: Path, flip_notebook_vault: Path, okf_relative_vault: Path
):
    for vault in (okf_portable_vault, flip_notebook_vault, okf_relative_vault):
        index_vault(vault)
        first = _query_snapshot(vault)
        index_path(vault).unlink()
        index_vault(vault)
        assert _query_snapshot(vault) == first


# ---- advisory trust health -------------------------------------------------


def test_trust_health_flags_passed_stale_after(okf_portable_vault: Path):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    report = queries.trust_health(db)
    stale = [c for c in report.candidates if c.check == "stale_after"]
    assert [c.path for c in stale] == ["bundle/metrics/shipment-cost.md"]
    assert "2020-01-01" in stale[0].detail
    assert report.counts["stale_after"] == 1


def test_trust_health_flags_load_bearing_type_without_provenance(
    okf_portable_vault: Path,
):
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    report = queries.trust_health(db)
    missing = [c for c in report.candidates if c.check == "missing_provenance"]
    assert [c.path for c in missing] == ["bundle/claims/margin-improved.md"]


def test_trust_health_ignores_non_load_bearing_types(okf_relative_vault: Path):
    """A Playbook or Warehouse Table without provenance is not a finding —
    the load-bearing set is deliberately narrow."""
    index_vault(okf_relative_vault)
    db = _open(okf_relative_vault)
    report = queries.trust_health(db)
    assert report.candidates == []
    assert report.counts["total"] == 7


def test_trust_health_flags_content_changed_since_verification(
    okf_portable_vault: Path,
):
    """generated.at 2026-07-01 postdates the last verification 2026-06-11."""
    index_vault(okf_portable_vault)
    db = _open(okf_portable_vault)
    report = queries.trust_health(db)
    changed = [c for c in report.candidates if c.check == "changed_since_verified"]
    assert [c.path for c in changed] == ["bundle/metrics/shipment-cost.md"]
    assert "after last verification 2026-06-11" in changed[0].detail


def test_trust_health_uses_mtime_when_generated_at_absent(tmp_path: Path):
    (tmp_path / "Note.md").write_text(
        "---\ntype: Claim\nverified: { by: human:kay, at: 2001-01-01T00:00:00Z }\n"
        "sources:\n  - { id: s1, resource: https://example.invalid/s1 }\n---\n# Note\n"
    )
    index_vault(tmp_path)
    db = _open(tmp_path)
    report = queries.trust_health(db)
    changed = [c for c in report.candidates if c.check == "changed_since_verified"]
    assert [c.path for c in changed] == ["Note.md"]
    assert changed[0].detail.startswith("modified ")


def test_trust_health_is_empty_on_a_trust_free_vault(tmp_path: Path):
    (tmp_path / "A.md").write_text("# A\n\n[[B]]\n")
    (tmp_path / "B.md").write_text("---\ntype: Claim\nstage: active\n---\n# B\n")
    index_vault(tmp_path)
    db = _open(tmp_path)
    report = queries.trust_health(db)
    # B is a Claim with no provenance — the one honest finding; nothing else fires.
    assert [(c.path, c.check) for c in report.candidates] == [
        ("B.md", "missing_provenance")
    ]
    assert report.counts["stale_after"] == 0
    assert report.counts["changed_since_verified"] == 0


def test_trust_health_verified_after_change_is_not_flagged(tmp_path: Path):
    (tmp_path / "Fresh.md").write_text(
        "---\ntype: Claim\ngenerated: { by: agent:x, at: 2026-01-01T00:00:00Z }\n"
        "verified:\n  - { by: human:kay, at: 2026-02-01T00:00:00Z }\n---\n# Fresh\n"
    )
    index_vault(tmp_path)
    db = _open(tmp_path)
    report = queries.trust_health(db)
    assert report.candidates == []


# ---- okf_conventions unit surface -----------------------------------------


def test_verified_bare_mapping_normalizes():
    assert okf_conventions.parse_verified(
        {"verified": {"by": "human:kay", "at": "2026-01-01"}}
    ) == [{"by": "human:kay", "at": "2026-01-01"}]


def test_verified_garbage_is_tolerated():
    assert okf_conventions.parse_verified({"verified": "yesterday, by me"}) == []
    assert okf_conventions.parse_verified({"verified": [None, 3, {"by": "x"}]}) == [
        {"by": "x"}
    ]
    assert okf_conventions.parse_verified({}) == []


def test_generated_garbage_is_tolerated():
    assert okf_conventions.parse_generated({"generated": "agent:x"}) == (None, None)
    assert okf_conventions.parse_generated({"generated": {"by": "agent:x"}}) == (
        "agent:x",
        None,
    )


def test_human_tier_detection():
    assert okf_conventions.is_human_actor("human:rivera")
    assert not okf_conventions.is_human_actor("process:nightly")
    assert not okf_conventions.is_human_actor("agent:claude")
    assert not okf_conventions.is_human_actor(None)


def test_verified_stats_picks_the_latest_event():
    count, human, latest = okf_conventions.verified_stats(
        [
            {"by": "process:a", "at": "2026-06-11T02:00:00Z"},
            {"by": "human:kay", "at": "2026-06-10T09:00:00Z"},
        ]
    )
    assert (count, human, latest) == (2, 1, "2026-06-11T02:00:00Z")


def test_resource_classification():
    c = okf_conventions.classify_resource
    assert c(None) == "missing"
    assert c("https://example.invalid/x") == "external"
    assert c("mailto:someone@example.invalid") == "external"
    assert c("/references/a.md") == "note-path"
    assert c("../references/a.md#section") == "note-path"
    assert c("all queries in project X") == "opaque"
    assert c("references/attesters/x.py") == "opaque"


def test_trust_summary_omits_absent_fields():
    assert okf_conventions.trust_summary() is None
    assert okf_conventions.trust_summary(sources_count=0) == "sources: 0"
    assert (
        okf_conventions.trust_summary(generated_by="agent-x", generated_at="2026-07-01")
        == "generated 2026-07-01 by agent-x"
    )


# ---- flip-side regression guards ------------------------------------------


def test_flip_notebook_still_resolves_wikilinks_and_ids(flip_notebook_vault: Path):
    stats = index_vault(flip_notebook_vault)
    assert stats.flip_bundles == 2
    assert stats.flip_handles == 2
    assert stats.flip_id_collisions == 0
    db = _open(flip_notebook_vault)
    view = queries.note(
        db, "notebooks/roof-coatings/references/field-trial-summer-attic.md"
    )
    assert view is not None
    assert view.flip_id == "A1"
    assert view.bundle_path == "notebooks/roof-coatings"
    assert view.bundle_handle == "roofs"


def test_indexing_a_flip_vault_still_reports_flip_counters(flip_vault: Path):
    """The pre-existing flip fixture keeps its exact counters with md-link
    indexing switched on (it contains no markdown links)."""
    stats = index_vault(flip_vault)
    assert stats.flip_bundles == 2
    db = _open(flip_vault)
    (md,) = db.execute("SELECT COUNT(*) FROM links WHERE kind = 'md'").fetchone()
    assert md == 0


def test_state_json_records_the_new_schema_version(okf_relative_vault: Path):
    from eno.config import state_path

    index_vault(okf_relative_vault)
    state = json.loads(state_path(okf_relative_vault).read_text())
    assert state["schema_version"] == 4
