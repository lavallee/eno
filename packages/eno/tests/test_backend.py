"""Tests for the backend abstraction. LocalBackend is exercised end-to-end;
ServiceBackend is exercised by injecting a mock client."""

from pathlib import Path

from eno.backend import LocalBackend, ServiceBackend, make_backend
from eno.indexer import index_vault


def _seed_vault(tmp_path: Path) -> None:
    (tmp_path / "A.md").write_text("# A\n\nlink to [[B]] and [[Imaginary]]\n")
    (tmp_path / "B.md").write_text("---\norigin: human\nstage: active\n---\n# B\n\nback to [[A]]\n")
    (tmp_path / "Orphan.md").write_text("# Orphan\n\nnothing links here")


def test_local_backend_orphans_and_excerpt(tmp_path: Path):
    _seed_vault(tmp_path)
    index_vault(tmp_path)
    backend = LocalBackend(tmp_path)

    orphans = backend.orphans()
    paths = [r.path for r in orphans]
    assert "Orphan.md" in paths
    assert "B.md" not in paths

    view = backend.note("B.md")
    assert view is not None
    assert view.title == "B"
    assert view.excerpt
    assert "back to" in view.excerpt


def test_local_backend_neighbors(tmp_path: Path):
    _seed_vault(tmp_path)
    index_vault(tmp_path)
    backend = LocalBackend(tmp_path)
    n = backend.neighbors("A.md")
    assert n is not None
    assert [r.path for r in n.outbound] == ["B.md"]
    assert [r.path for r in n.backlinks] == ["B.md"]


def test_local_backend_broken_links(tmp_path: Path):
    _seed_vault(tmp_path)
    index_vault(tmp_path)
    backend = LocalBackend(tmp_path)
    rows = backend.broken_links()
    assert len(rows) == 1
    assert rows[0].target_text == "Imaginary"


def test_make_backend_picks_service_when_url_set(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ENO_SERVICE_URL", "http://nowhere:9999")
    backend = make_backend()
    assert isinstance(backend, ServiceBackend)


def test_make_backend_picks_local_when_url_unset(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ENO_SERVICE_URL", raising=False)
    backend = make_backend(vault=tmp_path)
    assert isinstance(backend, LocalBackend)


def test_local_backend_create_note_reindexes(tmp_path: Path):
    """After create_note, the new note should be queryable via the same backend."""
    backend = LocalBackend(tmp_path)
    res = backend.create_note("New.md", "fresh content", author="Weaver")
    assert res.ok
    assert res.indexed
    # New note appears in search
    hits = backend.search("New")
    assert any(h.path == "New.md" for h in hits)


def test_local_backend_append_reindexes(tmp_path: Path):
    (tmp_path / "X.md").write_text("# X\n\nfirst\n")
    from eno.indexer import index_vault
    index_vault(tmp_path)
    backend = LocalBackend(tmp_path)
    res = backend.append_to_note("X.md", "appended content")
    assert res.ok
    assert res.indexed
    # Word count should reflect the new content
    view = backend.note("X.md", with_excerpt=False)
    assert view is not None
    assert view.word_count >= 4  # X + first + appended + content


def test_service_backend_hydrates_dataclasses(monkeypatch):
    """Inject a fake client to confirm dict→dataclass hydration is correct."""
    backend = ServiceBackend("http://x")

    class FakeClient:
        def get(self, path, params=None):
            if path == "/orphans":
                return [
                    {"path": "A.md", "title": "A", "word_count": 10, "excerpt": None}
                ]
            if path == "/note":
                return {
                    "path": "A.md",
                    "title": "A",
                    "word_count": 10,
                    "frontmatter": {"origin": "human"},
                    "headings": [{"level": 1, "text": "A", "line_no": 1}],
                    "excerpt": "hi",
                }
            return None

    backend.client = FakeClient()
    rows = backend.orphans()
    assert rows[0].path == "A.md"
    assert rows[0].word_count == 10

    view = backend.note("A.md")
    assert view.title == "A"
    assert view.frontmatter["origin"] == "human"
    assert view.headings[0].text == "A"
