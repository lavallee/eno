from pathlib import Path

from eno.excerpt import excerpt


def test_excerpt_strips_frontmatter_and_code(tmp_path: Path):
    raw = (
        "---\ntitle: X\n---\n\n# Heading\n\n"
        "This is the prose we want.\n\n"
        "```python\nimport secrets\n```\n\n"
        "Final paragraph."
    )
    (tmp_path / "X.md").write_text(raw)
    out = excerpt(tmp_path, "X.md")
    assert "secrets" not in out
    assert "title:" not in out
    assert "Heading" in out
    assert "prose we want" in out


def test_excerpt_respects_paragraph_boundary(tmp_path: Path):
    body = "First paragraph " * 30 + "\n\n" + "Second paragraph " * 30
    (tmp_path / "X.md").write_text(f"# X\n\n{body}")
    out = excerpt(tmp_path, "X.md", max_chars=200)
    assert out.endswith("…")
    assert len(out) <= 200 + 5


def test_excerpt_returns_empty_for_missing(tmp_path: Path):
    assert excerpt(tmp_path, "nonexistent.md") == ""


def test_excerpt_short_note_returns_full_text(tmp_path: Path):
    (tmp_path / "X.md").write_text("# Hi\n\nshort note here")
    out = excerpt(tmp_path, "X.md")
    assert out == "Hi\n\nshort note here"
