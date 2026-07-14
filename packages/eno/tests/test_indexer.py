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
    assert state["schema_version"] == 1
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
