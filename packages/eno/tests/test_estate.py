import json
import sqlite3
from pathlib import Path

import pytest
from eno.config import index_path, state_path
from eno.estate import EstateRegistryError, load_estate_scope
from eno.indexer import index_vault
from eno.queries import search


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _notebook(root: Path, rel: str, *, uid: str = "", body: str = "") -> Path:
    uid_line = f"uid: {uid}\n" if uid else ""
    path = _write(
        root,
        f"{rel}/index.md",
        "---\n"
        'okf_version: "0.2"\n'
        'flip: "0.9"\n'
        f"slug: {Path(rel).name}\n"
        f"{uid_line}"
        f"title: {Path(rel).name}\n"
        "---\n"
        f"# {Path(rel).name}\n\n{body}\n",
    )
    return path.parent


def _registry(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_estate_selects_one_lineage_and_composes_full_root(tmp_path: Path):
    central = tmp_path / "Central"
    _write(central, "Operator.md", "# Operator\n\nShared research market signal.\n")
    canonical = _notebook(
        tmp_path,
        "alpha/notebooks/market",
        uid="nb-market1",
        body="Shared research market signal.",
    )
    copy = _notebook(
        tmp_path,
        "alpha-long-copy/notebooks/market",
        uid="nb-market1",
        body="Old duplicate checkout.",
    )
    legacy = _notebook(
        tmp_path,
        "legacy/notebooks/topic",
        body="Legacy notebook without lineage identity.",
    )
    hidden = _notebook(
        tmp_path,
        ".worktrees/alpha/notebooks/market",
        uid="nb-market1",
        body="Worktree copy.",
    )
    registry = _registry(
        tmp_path / "flip-index.jsonl",
        [
            {"path": str(copy), "slug": "market", "uid": "nb-market1"},
            {"path": str(canonical), "slug": "market", "uid": "nb-market1"},
            {"path": str(legacy), "slug": "topic", "uid": ""},
            {"path": str(hidden), "slug": "market", "uid": "nb-market1"},
            {"path": str(tmp_path), "workspace": True, "notebooks": {}},
        ],
    )

    scope = load_estate_scope(tmp_path, registry, include_roots=[Path("Central")])

    assert [p.relative_to(tmp_path).as_posix() for p in scope.roots] == [
        "Central",
        "alpha/notebooks/market",
        "legacy/notebooks/topic",
    ]
    assert scope.notebooks_discovered == 3
    assert scope.notebooks_indexed == 2
    assert scope.duplicate_lineages == 1
    assert scope.shadowed_copies == 1
    assert scope.missing_uids == 1
    assert scope.ignored_hidden_copies == 1
    assert scope.shadows["nb-market1"]["selected"] == "alpha/notebooks/market"

    stats = index_vault(tmp_path, estate=scope)
    assert stats.scope == "flip-estate"
    assert stats.notebooks_indexed == 2
    db = sqlite3.connect(index_path(tmp_path))
    paths = {row[0] for row in db.execute("SELECT path FROM notes")}
    assert "Central/Operator.md" in paths
    assert "alpha/notebooks/market/index.md" in paths
    assert "legacy/notebooks/topic/index.md" in paths
    assert not any("alpha-long-copy" in path for path in paths)
    assert not any(".worktrees" in path for path in paths)
    hits = search(db, "shared research market signal", kind="text")
    assert {hit.path for hit in hits} == {
        "Central/Operator.md",
        "alpha/notebooks/market/index.md",
    }
    state = json.loads(state_path(tmp_path).read_text(encoding="utf-8"))
    assert state["scope"]["shadowed_copies"] == 1
    assert state["scope"]["shadows"]["nb-market1"]["selected"] == ("alpha/notebooks/market")


def test_estate_rejects_registry_path_outside_root(tmp_path: Path):
    outside = _notebook(tmp_path.parent / "outside-estate", "notebook", uid="nb-outside1")
    registry = _registry(
        tmp_path / "index.jsonl",
        [{"path": str(outside), "slug": "outside", "uid": "nb-outside1"}],
    )
    with pytest.raises(EstateRegistryError, match="escapes estate root"):
        load_estate_scope(tmp_path, registry)


def test_estate_rejects_corrupt_registry(tmp_path: Path):
    registry = tmp_path / "index.jsonl"
    registry.write_text("not json\n", encoding="utf-8")
    with pytest.raises(EstateRegistryError, match="line 1"):
        load_estate_scope(tmp_path, registry)
