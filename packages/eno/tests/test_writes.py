"""Tests for vault write operations: create_note, append_to_note, path safety."""

from pathlib import Path

import yaml
from eno.writes import (
    _insert_under_heading,
    _safe_vault_path,
    append_to_note,
    create_note,
)

# ---- path safety ---------------------------------------------------------


def test_safe_path_rejects_absolute(tmp_path: Path):
    assert _safe_vault_path(tmp_path, "/etc/passwd") is None


def test_safe_path_rejects_dotdot(tmp_path: Path):
    assert _safe_vault_path(tmp_path, "../escape.md") is None


def test_safe_path_rejects_system_dirs(tmp_path: Path):
    assert _safe_vault_path(tmp_path, ".eno/index.db") is None
    assert _safe_vault_path(tmp_path, ".git/HEAD") is None
    assert _safe_vault_path(tmp_path, ".obsidian/workspace") is None


def test_safe_path_accepts_normal(tmp_path: Path):
    p = _safe_vault_path(tmp_path, "2 Projects/Foo.md")
    assert p == (tmp_path / "2 Projects/Foo.md").resolve()


def test_safe_path_allows_9_vault_health(tmp_path: Path):
    """`9 Vault Health/` is a normal vault folder, not a system dir."""
    p = _safe_vault_path(tmp_path, "9 Vault Health/2026-04-30-garden.md")
    assert p is not None


# ---- create_note ---------------------------------------------------------


def test_create_note_writes_with_default_frontmatter(tmp_path: Path):
    res = create_note(tmp_path, "Foo", "some body content", author="Weaver")
    assert res.ok
    assert (tmp_path / "Foo.md").exists()
    raw = (tmp_path / "Foo.md").read_text()
    assert raw.startswith("---\n")
    fm_end = raw.index("\n---\n", 4)
    fm = yaml.safe_load(raw[4:fm_end])
    assert fm["origin"] == "llm"
    assert fm["author"] == "[[Weaver]]"
    assert "created" in fm
    assert "updated" in fm
    assert "title" in fm
    assert "# Foo" in raw
    assert "some body content" in raw


def test_create_note_appends_md_extension_if_missing(tmp_path: Path):
    res = create_note(tmp_path, "Foo", "body")
    assert res.ok
    assert res.path == "Foo.md"


def test_create_note_refuses_existing_without_overwrite(tmp_path: Path):
    (tmp_path / "X.md").write_text("# X\n")
    res = create_note(tmp_path, "X.md", "body")
    assert not res.ok
    assert "exists" in res.error


def test_create_note_overwrite_replaces(tmp_path: Path):
    (tmp_path / "X.md").write_text("old content")
    res = create_note(tmp_path, "X.md", "new body", overwrite=True)
    assert res.ok
    raw = (tmp_path / "X.md").read_text()
    assert "new body" in raw
    assert "old content" not in raw


def test_create_note_rejects_system_path(tmp_path: Path):
    res = create_note(tmp_path, ".git/sneaky.md", "body")
    assert not res.ok
    assert "invalid path" in res.error


def test_create_note_creates_nested_dirs(tmp_path: Path):
    res = create_note(tmp_path, "deep/nest/Note.md", "body")
    assert res.ok
    assert (tmp_path / "deep/nest/Note.md").exists()


def test_create_note_uses_env_author(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ENO_AGENT_NAME", "Claude Code")
    res = create_note(tmp_path, "Foo.md", "body")
    assert res.ok
    raw = (tmp_path / "Foo.md").read_text()
    assert "[[Claude Code]]" in raw


def test_create_note_with_explicit_frontmatter(tmp_path: Path):
    res = create_note(
        tmp_path,
        "X.md",
        "body",
        frontmatter={"title": "Custom", "type": "research", "stage": "draft"},
    )
    assert res.ok
    raw = (tmp_path / "X.md").read_text()
    fm = yaml.safe_load(raw[4 : raw.index("\n---\n", 4)])
    assert fm["title"] == "Custom"
    assert fm["type"] == "research"
    assert fm["stage"] == "draft"


# ---- append_to_note ------------------------------------------------------


def test_append_at_end(tmp_path: Path):
    (tmp_path / "X.md").write_text("# X\n\nfirst paragraph\n")
    res = append_to_note(tmp_path, "X.md", "second paragraph")
    assert res.ok
    raw = (tmp_path / "X.md").read_text()
    assert raw.endswith("second paragraph\n")
    assert "first paragraph" in raw


def test_append_under_heading(tmp_path: Path):
    raw = "# X\n\n## State\n\nold state\n\n## Other\n\nstuff\n"
    (tmp_path / "X.md").write_text(raw)
    res = append_to_note(
        tmp_path, "X.md", "new state line", under_heading="## State"
    )
    assert res.ok
    new_raw = (tmp_path / "X.md").read_text()
    # Insertion must be inside ## State, before ## Other
    state_pos = new_raw.index("## State")
    other_pos = new_raw.index("## Other")
    new_pos = new_raw.index("new state line")
    assert state_pos < new_pos < other_pos


def test_append_under_heading_at_eof(tmp_path: Path):
    raw = "# X\n\n## State\n\nthe only content\n"
    (tmp_path / "X.md").write_text(raw)
    res = append_to_note(
        tmp_path, "X.md", "addendum", under_heading="## State"
    )
    assert res.ok
    new_raw = (tmp_path / "X.md").read_text()
    assert "addendum" in new_raw
    # Should land after "the only content"
    assert new_raw.index("the only content") < new_raw.index("addendum")


def test_append_heading_not_found(tmp_path: Path):
    (tmp_path / "X.md").write_text("# X\n\n## State\n")
    res = append_to_note(
        tmp_path, "X.md", "stuff", under_heading="## Nonexistent"
    )
    assert not res.ok
    assert "heading not found" in res.error


def test_append_to_missing_note(tmp_path: Path):
    res = append_to_note(tmp_path, "Missing.md", "stuff")
    assert not res.ok
    assert "not found" in res.error


def test_append_rejects_system_path(tmp_path: Path):
    res = append_to_note(tmp_path, ".eno/something.md", "stuff")
    assert not res.ok


# ---- _insert_under_heading edge cases ------------------------------------


def test_insert_skips_headings_inside_code_fences():
    raw = "# X\n\n## Real\n\n```\n## Fake heading\n```\n\n## Other\n"
    out = _insert_under_heading(raw, "## Real", "inserted")
    # Insertion must land before ## Other, not inside the fenced block
    assert "inserted" in out
    real_pos = out.index("## Real")
    other_pos = out.index("## Other")
    inserted_pos = out.index("inserted")
    assert real_pos < inserted_pos < other_pos


def test_insert_returns_none_for_invalid_heading_format():
    assert _insert_under_heading("# X\n## Y\n", "not a heading", "x") is None


def test_insert_handles_higher_level_terminator():
    """Section bounded by an H1 should stop there, not slide into it."""
    raw = "# Page\n\n## Sub\n\nbody\n\n# Next Page\n\nother\n"
    out = _insert_under_heading(raw, "## Sub", "extra")
    sub_pos = out.index("## Sub")
    next_pos = out.index("# Next Page")
    extra_pos = out.index("extra")
    assert sub_pos < extra_pos < next_pos
