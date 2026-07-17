"""Tests for tool functions, exercised against a fixture vault via LocalBackend.
The MCP wire layer is not tested here — that's FastMCP's job. We test that each
tool returns the right shape on success and a clean error dict on failure."""

from pathlib import Path

import pytest
from eno.indexer import index_vault
from eno_mcp import tools


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "Alpha.md").write_text(
        "---\norigin: human\nstage: active\n---\n# Alpha\n\n[[Beta]] [[Imaginary]]\n"
    )
    (tmp_path / "Beta.md").write_text("# Beta\n\n[[Alpha]]\n")
    (tmp_path / "Orphan.md").write_text("# Orphan\n\nshort and unlinked")
    monkeypatch.setenv("ENO_VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("ENO_DIR", str(tmp_path / ".eno"))
    monkeypatch.delenv("ENO_SERVICE_URL", raising=False)
    index_vault(tmp_path)
    return tmp_path


def test_search_finds_by_title(vault):
    out = tools.eno_search("alpha")
    assert "hits" in out
    paths = [h["path"] for h in out["hits"]]
    assert "Alpha.md" in paths


def test_search_invalid_kind_returns_error_dict(vault):
    out = tools.eno_search("x", kind="bogus")
    assert "error" in out
    assert "hint" in out


def test_note_returns_view_with_excerpt(vault):
    out = tools.eno_note("Alpha.md")
    assert out["title"] == "Alpha"
    assert out["frontmatter"]["origin"] == "human"
    assert out["excerpt"]
    assert any(h["text"] == "Alpha" for h in out["headings"])


def test_note_missing_returns_null(vault):
    out = tools.eno_note("Nope.md")
    assert out["note"] is None
    assert "hint" in out


def test_neighbors(vault):
    out = tools.eno_neighbors("Alpha.md")
    backlink_paths = [b["path"] for b in out["backlinks"]]
    assert "Beta.md" in backlink_paths


def test_neighbors_missing(vault):
    out = tools.eno_neighbors("Nope.md")
    assert out["neighborhood"] is None


def test_orphans(vault):
    out = tools.eno_orphans()
    paths = [r["path"] for r in out["orphans"]]
    assert "Orphan.md" in paths
    assert out["count"] == len(out["orphans"])


def test_orphans_folder_filter_empty(vault):
    out = tools.eno_orphans(folder="DoesNotExist")
    assert out["count"] == 0


def test_stubs(vault):
    out = tools.eno_stubs(max_words=20)
    paths = [r["path"] for r in out["stubs"]]
    assert "Orphan.md" in paths


def test_stale_recent_files_returns_empty(vault):
    out = tools.eno_stale(older_than_days=180)
    assert out["count"] == 0


def test_broken_links_includes_imaginary(vault):
    out = tools.eno_broken_links()
    targets = [b["target_text"] for b in out["links"]]
    assert "Imaginary" in targets


def test_hygiene(vault):
    out = tools.eno_hygiene()
    # Beta and Orphan have no frontmatter; Alpha has both required fields.
    assert out["counts"]["origin"] == 2
    assert out["counts"]["stage"] == 2
    assert out["counts"]["total"] == 3


def test_concepts_returns_incipient_links(vault):
    out = tools.eno_concepts()
    assert "concepts" in out
    targets = [c["target_text"] for c in out["concepts"]]
    assert "Imaginary" in targets


def test_drift_returns_fuzzy_matches(tmp_path: Path, monkeypatch):
    # Drift case: target almost matches existing note
    (tmp_path / "Real Note.md").write_text("# Real Note\n")
    (tmp_path / "Caller.md").write_text("# Caller\n\n[[Real Notes]]\n")
    monkeypatch.setenv("ENO_VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("ENO_DIR", str(tmp_path / ".eno"))
    monkeypatch.delenv("ENO_SERVICE_URL", raising=False)
    from eno.indexer import index_vault
    index_vault(tmp_path)
    out = tools.eno_drift()
    assert out["count"] == 1
    assert out["drift"][0]["target_text"] == "Real Notes"
    assert out["drift"][0]["suggested_path"] == "Real Note.md"


@pytest.fixture()
def flip_vault(tmp_path: Path, monkeypatch) -> Path:
    bundle = tmp_path / "research" / "hosm"
    (bundle / "references").mkdir(parents=True)
    (bundle / "index.md").write_text('---\nokf_version: "0.4"\nflip: "0.4"\n---\n# HOSM\n')
    (bundle / "references" / "paper.md").write_text(
        "---\nid: A1\naliases: [A1]\n---\n# Paper\n\n[[Q9]] [[Some Concept]]\n"
    )
    (tmp_path / ".flip").mkdir()
    (tmp_path / ".flip" / "workspace.toml").write_text('[notebooks]\nhosm = "research/hosm"\n')
    monkeypatch.setenv("ENO_VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("ENO_DIR", str(tmp_path / ".eno"))
    monkeypatch.delenv("ENO_SERVICE_URL", raising=False)
    index_vault(tmp_path)
    return tmp_path


def test_eno_note_returns_flip_fields(flip_vault):
    out = tools.eno_note("research/hosm/references/paper.md")
    assert out["flip_id"] == "A1"
    assert out["bundle_path"] == "research/hosm"
    assert out["bundle_handle"] == "hosm"
    # Plain notes on flip-free vaults keep the keys, null-valued (additive shape).


def test_eno_note_flip_fields_null_on_plain_vault(vault):
    out = tools.eno_note("Alpha.md")
    assert out["flip_id"] is None
    assert out["bundle_path"] is None
    assert out["bundle_handle"] is None


def test_eno_concepts_excludes_flip_refs(flip_vault):
    out = tools.eno_concepts()
    targets = [c["target_text"] for c in out["concepts"]]
    assert "Some Concept" in targets
    assert "Q9" not in targets  # id-shaped ref on a flip vault: flip ref, not concept


def test_concepts_limit_respected(vault):
    out = tools.eno_concepts(limit=0)
    assert out["concepts"] == []


def test_hot_returns_bundle(vault):
    out = tools.eno_hot(agent_name="Weaver")
    assert out["agent_name"] == "Weaver"
    assert out["generated_at"]
    assert "frontier" in out
    assert "recent_appends" in out
    assert "top_concepts" in out
    assert "agent_recent" in out
    # Imaginary is an incipient concept on the fixture
    targets = [c["target_text"] for c in out["top_concepts"]]
    assert "Imaginary" in targets


def test_hot_reads_agent_from_env(vault, monkeypatch):
    monkeypatch.setenv("ENO_AGENT_NAME", "Weaver")
    out = tools.eno_hot()
    assert out["agent_name"] == "Weaver"


def test_create_note_via_mcp(vault):
    out = tools.eno_create_note(
        path="WeaverNote.md",
        body="written by weaver",
        author="Weaver",
    )
    assert out["ok"]
    assert out["indexed"]
    assert (vault / "WeaverNote.md").exists()
    raw = (vault / "WeaverNote.md").read_text()
    assert "[[Weaver]]" in raw
    assert "written by weaver" in raw


def test_create_note_refuses_existing_via_mcp(vault):
    out = tools.eno_create_note(path="Alpha.md", body="x")
    assert not out["ok"]
    assert "exists" in out["error"]


def test_append_to_note_via_mcp(vault):
    out = tools.eno_append_to_note(
        path="Beta.md", content="appended via mcp"
    )
    assert out["ok"]
    assert "appended via mcp" in (vault / "Beta.md").read_text()


def test_append_under_heading_via_mcp(vault):
    (vault / "Sectioned.md").write_text(
        "# Sectioned\n\n## State\n\nfirst\n\n## Other\n\nstuff\n"
    )
    out = tools.eno_append_to_note(
        path="Sectioned.md",
        content="under-state line",
        under_heading="## State",
    )
    assert out["ok"]
    raw = (vault / "Sectioned.md").read_text()
    state_pos = raw.index("## State")
    other_pos = raw.index("## Other")
    assert state_pos < raw.index("under-state line") < other_pos


def test_health_local_ok(vault):
    out = tools.eno_health()
    assert out["ok"] is True
    assert out["mode"] == "local"


def test_health_local_no_index(tmp_path: Path, monkeypatch):
    """Without running index_vault, health reports the missing index."""
    monkeypatch.setenv("ENO_VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("ENO_DIR", str(tmp_path / ".eno"))
    monkeypatch.delenv("ENO_SERVICE_URL", raising=False)
    out = tools.eno_health()
    assert out["ok"] is False
    assert "no index" in out["hint"]


def test_health_service_mode_uses_service_url(monkeypatch):
    """When ENO_SERVICE_URL is set, eno_health pings the service."""
    monkeypatch.setenv("ENO_SERVICE_URL", "http://service.invalid:9999")
    out = tools.eno_health()
    assert "error" in out
    assert "unreachable" in out["error"]
