"""End-to-end server tests via FastAPI's TestClient. Confirms wiring,
not query semantics (those live in test_queries.py)."""

from pathlib import Path

import pytest
from eno.indexer import index_vault
from eno_service.server import create_app
from fastapi.testclient import TestClient


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "Alpha.md").write_text(
        "---\norigin: human\nstage: active\n---\n# Alpha\n\nlink to [[Beta]] and [[Ghost]]\n"
    )
    (tmp_path / "Beta.md").write_text("# Beta\n\nback to [[Alpha]]\n")
    (tmp_path / "Orphan.md").write_text("# Orphan\n\nnothing inbound")
    monkeypatch.setenv("ENO_VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("ENO_DIR", str(tmp_path / ".eno"))
    index_vault(tmp_path)
    return tmp_path


@pytest.fixture()
def client(vault: Path) -> TestClient:
    return TestClient(create_app())


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True


def test_search(client: TestClient):
    r = client.get("/search", params={"q": "alpha"})
    assert r.status_code == 200
    paths = [h["path"] for h in r.json()]
    assert "Alpha.md" in paths


def test_note_returns_view_with_excerpt(client: TestClient):
    r = client.get("/note", params={"path": "Alpha.md"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Alpha"
    assert body["frontmatter"]["origin"] == "human"
    assert body["excerpt"]


def test_note_404(client: TestClient):
    r = client.get("/note", params={"path": "Nope.md"})
    assert r.status_code == 404


def test_neighbors(client: TestClient):
    r = client.get("/neighbors", params={"path": "Alpha.md"})
    assert r.status_code == 200
    body = r.json()
    assert any(b["path"] == "Beta.md" for b in body["backlinks"])
    assert any(o["path"] == "Beta.md" for o in body["outbound"])


def test_orphans(client: TestClient):
    r = client.get("/orphans")
    assert r.status_code == 200
    paths = [n["path"] for n in r.json()]
    assert "Orphan.md" in paths


def test_broken_links(client: TestClient):
    r = client.get("/broken-links")
    assert r.status_code == 200
    targets = [b["target_text"] for b in r.json()]
    assert "Ghost" in targets


def test_hot(client: TestClient):
    r = client.get("/hot", params={"agent_name": "Weaver"})
    assert r.status_code == 200
    body = r.json()
    assert body["agent_name"] == "Weaver"
    assert body["generated_at"]
    # Fixture has Alpha→Beta+Ghost (out=1, in=1, score=0 → not in default frontier),
    # but recent_appends should at least include some notes.
    assert isinstance(body["frontier"], list)
    assert isinstance(body["recent_appends"], list)
    assert isinstance(body["top_concepts"], list)
    assert isinstance(body["agent_recent"], list)


def test_frontier(client: TestClient):
    r = client.get("/frontier")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # Alpha → Beta + Ghost: out=1 (Beta resolves; Ghost doesn't), in=1 (Beta).
    # Score = 0 by default; expect Alpha excluded unless include_nonpositive.
    r2 = client.get("/frontier", params={"include_nonpositive": "true"})
    assert r2.status_code == 200
    paths = [f["path"] for f in r2.json()]
    assert "Alpha.md" in paths


def test_hygiene(client: TestClient):
    r = client.get("/hygiene")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["total"] == 3
    # Beta and Orphan lack frontmatter
    assert body["counts"]["origin"] == 2


def test_search_unknown_kind_400(client: TestClient):
    r = client.get("/search", params={"q": "x", "kind": "bogus"})
    assert r.status_code == 400


def test_hygiene_propose(client: TestClient):
    r = client.post("/hygiene/propose", json={"include_unknown": False})
    assert r.status_code == 200
    body = r.json()
    assert "proposals" in body
    assert body["total_notes"] >= 3
    paths = {p["path"] for p in body["proposals"]}
    # Alpha already has origin → not in proposals
    assert "Alpha.md" not in paths
    # Orphan and Beta lack origin → eligible
    assert "Beta.md" in paths or "Orphan.md" in paths


def test_classify_broken_links_endpoint(client: TestClient):
    r = client.get("/classify-broken-links")
    assert r.status_code == 200
    body = r.json()
    assert "drift" in body
    assert "concepts" in body
    # Alpha has [[Ghost]] which doesn't resolve and doesn't fuzzy-match anything
    targets = [c["target_text"] for c in body["concepts"]]
    assert "Ghost" in targets


def test_garden_endpoint(client: TestClient):
    r = client.post("/garden", json={})
    assert r.status_code == 200
    body = r.json()
    assert "resurfacing" in body
    assert "concepts" in body
    assert "drift" in body
    assert "duplicates" in body
    assert "stubs" in body
    assert "stale" in body
    assert "stats" in body


def test_create_note_endpoint(vault: Path, client: TestClient):
    r = client.post(
        "/note/create",
        json={
            "path": "FromService.md",
            "body": "service-created body",
            "author": "TestAgent",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"]
    assert data["indexed"]
    assert (vault / "FromService.md").exists()
    assert "[[TestAgent]]" in (vault / "FromService.md").read_text()


def test_create_note_endpoint_refuses_existing(vault: Path, client: TestClient):
    r = client.post(
        "/note/create",
        json={"path": "Alpha.md", "body": "should not overwrite"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_append_to_note_endpoint(vault: Path, client: TestClient):
    r = client.post(
        "/note/append",
        json={"path": "Beta.md", "content": "new line via service"},
    )
    assert r.status_code == 200
    assert r.json()["ok"]
    assert "new line via service" in (vault / "Beta.md").read_text()


def test_note_endpoint_includes_flip_fields(tmp_path: Path, monkeypatch):
    bundle = tmp_path / "research" / "hosm"
    (bundle / "references").mkdir(parents=True)
    (bundle / "index.md").write_text('---\nokf_version: "0.4"\nflip: "0.4"\n---\n# HOSM\n')
    (bundle / "references" / "paper.md").write_text("---\nid: A1\naliases: [A1]\n---\n# Paper\n")
    (tmp_path / ".flip").mkdir()
    (tmp_path / ".flip" / "workspace.toml").write_text('[notebooks]\nhosm = "research/hosm"\n')
    monkeypatch.setenv("ENO_VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("ENO_DIR", str(tmp_path / ".eno"))
    index_vault(tmp_path)
    client = TestClient(create_app())

    r = client.get("/note", params={"path": "research/hosm/references/paper.md"})
    assert r.status_code == 200
    body = r.json()
    assert body["flip_id"] == "A1"
    assert body["bundle_path"] == "research/hosm"
    assert body["bundle_handle"] == "hosm"


def test_note_endpoint_flip_fields_null_on_plain_vault(client: TestClient):
    r = client.get("/note", params={"path": "Alpha.md"})
    assert r.status_code == 200
    body = r.json()
    assert body["flip_id"] is None
    assert body["bundle_path"] is None
    assert body["bundle_handle"] is None


def test_garden_endpoint_includes_flip_refs(client: TestClient):
    r = client.post("/garden", json={})
    assert r.status_code == 200
    body = r.json()
    assert "flip_refs" in body
    assert body["flip_refs"] == []  # plain fixture vault has no flip bundles


def test_hygiene_apply(vault: Path, client: TestClient):
    proposals = [
        {
            "path": "Beta.md",
            "add": {"origin": "human"},
            "confidence": "medium",
            "reason": "test",
        }
    ]
    r = client.post(
        "/hygiene/apply", json={"proposals": proposals, "dry_run": False}
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0]["ok"]
    assert results[0]["applied"] == {"origin": "human"}
    # Verify the file was actually mutated
    new = (vault / "Beta.md").read_text()
    assert "origin: human" in new
    assert new.startswith("---\n")
