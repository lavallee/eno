import os
import sqlite3
from pathlib import Path

from eno.config import index_path, state_path
from eno.indexer import index_vault


def _write(vault: Path, rel: str, content: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_indexes_simple_vault(tmp_path: Path):
    _write(
        tmp_path,
        "Alpha.md",
        "---\ntitle: Alpha\ntags: [project]\n---\n# Alpha\n\nLink to [[Beta]] and [[Gamma]]\n",
    )
    _write(tmp_path, "Beta.md", "# Beta\n\nlink back to [[Alpha]]\n")
    _write(tmp_path, "notes/Gamma.md", "---\naliases: [Gee]\n---\n# Gamma\n\nstandalone\n")
    _write(tmp_path, "Orphan.md", "# Orphan\n\nno links\n")

    stats = index_vault(tmp_path)
    assert stats.parsed == 4
    assert stats.skipped_unchanged == 0

    db = sqlite3.connect(index_path(tmp_path))
    paths = sorted(r[0] for r in db.execute("SELECT path FROM notes"))
    assert paths == ["Alpha.md", "Beta.md", "Orphan.md", "notes/Gamma.md"]

    alpha_targets = sorted(
        db.execute(
            "SELECT target_text, target_path FROM links WHERE src_path = 'Alpha.md' ORDER BY target_text"
        ).fetchall()
    )
    assert alpha_targets == [("Beta", "Beta.md"), ("Gamma", "notes/Gamma.md")]

    # Beta -> Alpha resolves
    beta_target = db.execute(
        "SELECT target_path FROM links WHERE src_path = 'Beta.md'"
    ).fetchone()
    assert beta_target == ("Alpha.md",)

    # Tag persisted
    assert ("Alpha.md", "project") in db.execute("SELECT path, tag FROM tags").fetchall()

    # Alias persisted
    assert ("notes/Gamma.md", "Gee") in db.execute(
        "SELECT path, alias FROM aliases"
    ).fetchall()


def test_orphan_query(tmp_path: Path):
    _write(tmp_path, "A.md", "# A\n\nlink to [[B]]\n")
    _write(tmp_path, "B.md", "# B\n")
    _write(tmp_path, "Orphan.md", "# Orphan\n")
    index_vault(tmp_path)
    db = sqlite3.connect(index_path(tmp_path))
    orphans = [
        r[0]
        for r in db.execute(
            """
            SELECT path FROM notes
            WHERE path NOT IN (
                SELECT target_path FROM links WHERE target_path IS NOT NULL
            )
            ORDER BY path
            """
        )
    ]
    assert "Orphan.md" in orphans
    assert "A.md" in orphans  # nothing links to A
    assert "B.md" not in orphans


def test_alias_resolution(tmp_path: Path):
    _write(tmp_path, "Real.md", "---\naliases: [Nick]\n---\n# Real\n")
    _write(tmp_path, "Caller.md", "# Caller\n\nlink via alias [[Nick]]\n")
    index_vault(tmp_path)
    db = sqlite3.connect(index_path(tmp_path))
    target = db.execute(
        "SELECT target_path FROM links WHERE src_path = 'Caller.md'"
    ).fetchone()
    assert target == ("Real.md",)


def test_broken_link_left_null(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n\nlink to [[NotThere]]\n")
    stats = index_vault(tmp_path)
    assert stats.links_broken == 1
    db = sqlite3.connect(index_path(tmp_path))
    target = db.execute("SELECT target_path FROM links").fetchone()
    assert target == (None,)


def test_incremental_skips_unchanged(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n")
    s1 = index_vault(tmp_path)
    assert s1.parsed == 1
    s2 = index_vault(tmp_path)
    assert s2.parsed == 0
    assert s2.skipped_unchanged == 1


def test_full_reindex_reparses(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n")
    index_vault(tmp_path)
    s2 = index_vault(tmp_path, full=True)
    assert s2.parsed == 1
    assert s2.skipped_unchanged == 0


def test_deleted_note_removed(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n")
    _write(tmp_path, "Y.md", "# Y\n")
    s1 = index_vault(tmp_path)
    assert s1.parsed == 2
    (tmp_path / "Y.md").unlink()
    s2 = index_vault(tmp_path)
    assert s2.deleted == 1
    db = sqlite3.connect(index_path(tmp_path))
    paths = [r[0] for r in db.execute("SELECT path FROM notes")]
    assert paths == ["X.md"]


def test_modified_note_relinks(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n\n[[A]]\n")
    _write(tmp_path, "A.md", "# A\n")
    _write(tmp_path, "B.md", "# B\n")
    index_vault(tmp_path)
    # Touch X to bump mtime, change link to point to B instead
    (tmp_path / "X.md").write_text("# X\n\n[[B]]\n")
    os.utime(tmp_path / "X.md", (1e9, 2e9))  # ensure mtime distinct
    index_vault(tmp_path)
    db = sqlite3.connect(index_path(tmp_path))
    targets = sorted(
        r[0] for r in db.execute("SELECT target_path FROM links WHERE src_path = 'X.md'")
    )
    assert targets == ["B.md"]


def test_skip_obsidian_and_eno_dirs(tmp_path: Path):
    _write(tmp_path, ".obsidian/workspace.md", "# noise\n")
    _write(tmp_path, ".eno/cache/foo.md", "# also noise\n")
    _write(tmp_path, "Real.md", "# Real\n")
    stats = index_vault(tmp_path)
    assert stats.parsed == 1
    db = sqlite3.connect(index_path(tmp_path))
    paths = [r[0] for r in db.execute("SELECT path FROM notes")]
    assert paths == ["Real.md"]


def test_state_json_written(tmp_path: Path):
    _write(tmp_path, "X.md", "# X\n")
    index_vault(tmp_path)
    sp = state_path(tmp_path)
    assert sp.exists()
    import json

    state = json.loads(sp.read_text())
    assert state["schema_version"] == 2
    assert "last_full_index_at" in state
    assert state["stats"]["parsed"] == 1


def test_eno_dir_env_override(tmp_path: Path, monkeypatch):
    """ENO_DIR redirects index/state out of the vault — useful for smoke tests."""
    _write(tmp_path, "X.md", "# X\n")
    sidecar = tmp_path.parent / "eno-sidecar"
    monkeypatch.setenv("ENO_DIR", str(sidecar))
    index_vault(tmp_path)
    assert (sidecar / "index.db").exists()
    assert (sidecar / "state.json").exists()
    assert not (tmp_path / ".eno").exists()


# ---- flip awareness --------------------------------------------------------


def _target_of(db, src_path: str, target_text: str, anchor: str | None = None):
    sql = "SELECT target_path FROM links WHERE src_path = ? AND target_text = ?"
    params: list = [src_path, target_text]
    if anchor is not None:
        sql += " AND target_anchor = ?"
        params.append(anchor)
    row = db.execute(sql, params).fetchone()
    assert row is not None, f"no link {target_text!r} from {src_path!r}"
    return row[0]


def test_flip_free_vault_flip_columns_null(tmp_path: Path):
    _write(tmp_path, "Alpha.md", "# Alpha\n\n[[Beta]]\n")
    _write(tmp_path, "Beta.md", "# Beta\n")
    stats = index_vault(tmp_path)
    assert stats.flip_bundles == 0
    assert stats.flip_handles == 0
    assert stats.flip_id_collisions == 0
    db = sqlite3.connect(index_path(tmp_path))
    rows = db.execute("SELECT flip_id, bundle_path, bundle_handle FROM notes").fetchall()
    assert rows and all(r == (None, None, None) for r in rows)


def test_flip_free_vault_id_frontmatter_not_lifted(tmp_path: Path):
    """flip_id is only meaningful INSIDE a bundle: `id: Q4` frontmatter in a
    flip-free vault must not populate flip_id (would leak into note --json and
    garden's drift-candidate id tuples)."""
    _write(tmp_path, "Quarter.md", "---\nid: Q4\n---\n# Quarter\n")
    _write(tmp_path, "Other.md", "# Other\n\n[[Q4]]\n")
    stats = index_vault(tmp_path)
    assert stats.flip_bundles == 0
    db = sqlite3.connect(index_path(tmp_path))
    rows = db.execute("SELECT flip_id, bundle_path, bundle_handle FROM notes").fetchall()
    assert rows and all(r == (None, None, None) for r in rows)
    # [[Q4]] is a plain broken link (Quarter.md has no Q4 basename/alias).
    assert _target_of(db, "Other.md", "Q4") is None


def test_id_frontmatter_outside_bundle_null_on_flip_vault(flip_vault: Path):
    """Same gate on a vault that DOES have bundles: an id-carrying note outside
    every bundle still gets flip_id NULL."""
    _write(flip_vault, "Loose.md", "---\nid: Q4\n---\n# Loose\n")
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    row = db.execute(
        "SELECT flip_id, bundle_path FROM notes WHERE path = 'Loose.md'"
    ).fetchone()
    assert row == (None, None)


def test_bundle_root_added_later_lifts_flip_id_incrementally(tmp_path: Path):
    """A bundle root created AFTER the entity note was indexed (and nulled) must
    re-lift flip_id from stored frontmatter on the next incremental run, even
    though the entity note itself is unchanged/skipped."""
    _write(tmp_path, "nb/ref.md", "---\nid: A1\naliases: [A1]\n---\n# Ref\n")
    index_vault(tmp_path)  # flip-free: flip_id nulled
    db = sqlite3.connect(index_path(tmp_path))
    assert db.execute("SELECT flip_id FROM notes WHERE path = 'nb/ref.md'").fetchone() == (None,)
    db.close()

    _write(tmp_path, "nb/index.md", '---\nokf_version: "0.4"\nflip: "0.4"\n---\n# NB\n')
    stats = index_vault(tmp_path)
    assert stats.flip_bundles == 1
    assert stats.parsed == 1  # only the new index.md; ref.md skipped unchanged
    db = sqlite3.connect(index_path(tmp_path))
    assert db.execute(
        "SELECT flip_id, bundle_path FROM notes WHERE path = 'nb/ref.md'"
    ).fetchone() == ("A1", "nb")


def test_bare_id_in_bundle_lacking_id_unresolved(flip_vault: Path):
    """Bundle-scoped bare-id lookup is TERMINAL: an id the containing bundle
    lacks stays unresolved — it must not fall through to the vault-wide alias
    map and cross-resolve to another bundle's A1 (walk-order nondeterminism)."""
    _write(
        flip_vault,
        "projects/solo/index.md",
        '---\nokf_version: "0.4"\nflip: "0.4"\n---\n# Solo\n',
    )
    _write(flip_vault, "projects/solo/note.md", "# Note\n\n[[A1]]\n")
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    assert _target_of(db, "projects/solo/note.md", "A1") is None
    # Outside-bundle notes are unaffected: [[A1]] from Notes.md still resolves
    # through the alias map as before.
    assert _target_of(db, "Notes.md", "A1") is not None


def test_bundle_root_detection_sets_bundle_path(flip_vault: Path):
    # Nested bundle: longest-prefix ancestor wins.
    _write(
        flip_vault,
        "research/hosm/nested/index.md",
        '---\nokf_version: "0.4"\nflip: "0.4"\n---\n# Nested\n',
    )
    _write(flip_vault, "research/hosm/nested/deep.md", "---\nid: Q1\n---\n# Deep\n")
    stats = index_vault(flip_vault)
    assert stats.flip_bundles == 3
    db = sqlite3.connect(index_path(flip_vault))
    bundle = dict(db.execute("SELECT path, bundle_path FROM notes"))
    assert bundle["research/hosm/references/paper-alpha.md"] == "research/hosm"
    assert bundle["research/hosm/index.md"] == "research/hosm"
    assert bundle["areas/frontier/threads/thread-two.md"] == "areas/frontier"
    assert bundle["research/hosm/nested/deep.md"] == "research/hosm/nested"
    assert bundle["Notes.md"] is None
    handles = dict(db.execute("SELECT path, bundle_handle FROM notes"))
    assert handles["research/hosm/claims/claim-one.md"] == "hosm"
    assert handles["areas/frontier/references/paper-beta.md"] == "front"
    assert handles["Notes.md"] is None


def test_flip_id_lifted(flip_vault: Path):
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    flip_ids = dict(db.execute("SELECT path, flip_id FROM notes"))
    assert flip_ids["research/hosm/references/paper-alpha.md"] == "A1"
    assert flip_ids["research/hosm/claims/claim-one.md"] == "C1"
    assert flip_ids["areas/frontier/threads/thread-two.md"] == "T2"
    assert flip_ids["research/hosm/index.md"] is None
    assert flip_ids["Notes.md"] is None


def test_bare_id_resolves_within_containing_bundle(flip_vault: Path):
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    assert (
        _target_of(db, "research/hosm/claims/claim-one.md", "A1")
        == "research/hosm/references/paper-alpha.md"
    )


def test_colliding_a1_resolves_per_bundle(flip_vault: Path):
    """The headline test: two bundles each hold an A1; bare [[A1]] resolves
    to the one in the CONTAINING bundle, not through first-wins aliases."""
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    assert (
        _target_of(db, "research/hosm/claims/claim-one.md", "A1")
        == "research/hosm/references/paper-alpha.md"
    )
    assert (
        _target_of(db, "areas/frontier/threads/thread-two.md", "A1")
        == "areas/frontier/references/paper-beta.md"
    )


def test_qualified_colon_resolves_via_workspace(flip_vault: Path):
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    assert (
        _target_of(db, "research/hosm/claims/claim-one.md", "front:A1")
        == "areas/frontier/references/paper-beta.md"
    )
    # Qualified refs also work from outside any bundle.
    assert _target_of(db, "Notes.md", "hosm:C1") == "research/hosm/claims/claim-one.md"


def test_hash_synonym_resolves(flip_vault: Path):
    """Deprecated [[front#T2]]: parser splits into target 'front' + anchor 'T2'."""
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    assert (
        _target_of(db, "research/hosm/claims/claim-one.md", "front", anchor="T2")
        == "areas/frontier/threads/thread-two.md"
    )


def test_hash_anchor_on_real_note_unchanged(flip_vault: Path):
    """A genuine note named like a handle keeps winning: [[Beta#Section]] → Beta.md."""
    _write(flip_vault, "Beta.md", "# Beta\n\n## Section\n")
    _write(flip_vault, "Caller.md", "# Caller\n\n[[Beta#Section]]\n")
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    assert _target_of(db, "Caller.md", "Beta", anchor="Section") == "Beta.md"


def test_unknown_handle_unresolved(flip_vault: Path):
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    assert _target_of(db, "research/hosm/claims/claim-one.md", "nope:A1") is None


def test_unknown_id_known_handle_unresolved(flip_vault: Path):
    index_vault(flip_vault)
    db = sqlite3.connect(index_path(flip_vault))
    assert _target_of(db, "research/hosm/claims/claim-one.md", "front:T9") is None


def test_same_bundle_duplicate_id_first_wins_and_counted(flip_vault: Path):
    _write(
        flip_vault,
        "research/hosm/references/zz-duplicate.md",
        "---\nid: A1\naliases: [A1]\n---\n# Duplicate A1\n",
    )
    stats = index_vault(flip_vault)
    assert stats.flip_id_collisions == 1
    db = sqlite3.connect(index_path(flip_vault))
    # First wins by path sort: paper-alpha.md < zz-duplicate.md
    assert (
        _target_of(db, "research/hosm/claims/claim-one.md", "A1")
        == "research/hosm/references/paper-alpha.md"
    )


def test_malformed_workspace_toml_does_not_crash_indexing(flip_vault: Path):
    (flip_vault / ".flip" / "workspace.toml").write_text("[[[garbage")
    stats = index_vault(flip_vault)
    assert stats.flip_bundles == 2
    assert stats.flip_handles == 0
    db = sqlite3.connect(index_path(flip_vault))
    # Qualified refs go unresolved; bundle-scoped bare ids still work.
    assert _target_of(db, "research/hosm/claims/claim-one.md", "front:A1") is None
    assert (
        _target_of(db, "research/hosm/claims/claim-one.md", "A1")
        == "research/hosm/references/paper-alpha.md"
    )


def test_workspace_entry_to_missing_bundle_ignored(flip_vault: Path):
    (flip_vault / ".flip" / "workspace.toml").write_text(
        '[notebooks]\nhosm = "research/hosm"\nfront = "areas/frontier"\n'
        'ghost = "nowhere/void"\n'
    )
    stats = index_vault(flip_vault)
    assert stats.flip_handles == 2  # ghost dropped: not a detected bundle dir
    db = sqlite3.connect(index_path(flip_vault))
    assert _target_of(db, "Notes.md", "hosm:C1") == "research/hosm/claims/claim-one.md"


def test_v1_index_db_rebuilt_on_open(tmp_path: Path):
    """A pre-flip index.db (user_version 0, old-shape tables) is dropped and
    rebuilt instead of crashing the new INSERT."""
    _write(tmp_path, "X.md", "# X\n\n[[Y]]\n")
    _write(tmp_path, "Y.md", "# Y\n")
    db_path = index_path(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(db_path)
    old.executescript(
        """
        CREATE TABLE notes (
            path TEXT PRIMARY KEY, title TEXT NOT NULL,
            word_count INTEGER NOT NULL DEFAULT 0, mtime REAL NOT NULL,
            content_hash TEXT NOT NULL, frontmatter_json TEXT NOT NULL DEFAULT '{}',
            origin TEXT, stage TEXT, type TEXT, created_at TEXT, updated_at TEXT,
            kind TEXT NOT NULL DEFAULT 'md', has_canvas INTEGER NOT NULL DEFAULT 0,
            indexed_at REAL NOT NULL
        );
        CREATE TABLE links (
            src_path TEXT NOT NULL, target_text TEXT NOT NULL,
            target_path TEXT, alias TEXT, line_no INTEGER NOT NULL
        );
        INSERT INTO notes VALUES ('Stale.md', 'Stale', 0, 1.0, 'x', '{}',
            NULL, NULL, NULL, NULL, NULL, 'md', 0, 1.0);
        """
    )
    old.commit()
    old.close()

    stats = index_vault(tmp_path)  # would crash on "no column named flip_id" without rebuild
    assert stats.parsed == 2  # full reparse: the rebuilt notes table came back empty
    db = sqlite3.connect(db_path)
    (uv,) = db.execute("PRAGMA user_version").fetchone()
    assert uv == 2
    paths = sorted(r[0] for r in db.execute("SELECT path FROM notes"))
    assert paths == ["X.md", "Y.md"]  # stale row gone
    assert _target_of(db, "X.md", "Y") == "Y.md"


def test_incremental_reindex_preserves_flip_resolution(flip_vault: Path):
    index_vault(flip_vault)
    s2 = index_vault(flip_vault)
    assert s2.parsed == 0
    assert s2.flip_bundles == 2
    db = sqlite3.connect(index_path(flip_vault))
    assert (
        _target_of(db, "research/hosm/claims/claim-one.md", "A1")
        == "research/hosm/references/paper-alpha.md"
    )
    assert (
        _target_of(db, "research/hosm/claims/claim-one.md", "front:A1")
        == "areas/frontier/references/paper-beta.md"
    )
