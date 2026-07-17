"""Shared fixtures. Repo convention is inline tmp_path construction per test;
the flip vault is the one fixture worth centralizing (used across indexer,
garden, and queries tests)."""

from pathlib import Path

import pytest


def make_flip_vault(root: Path) -> Path:
    """Two flip bundles (notebook + beat) with a colliding A1, a workspace
    handle table, and a vault note outside any bundle."""

    def w(rel: str, content: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    w(
        ".flip/workspace.toml",
        '[workspace]\nversion = "0.1"\n\n'
        '[notebooks]\nhosm = "research/hosm"\nfront = "areas/frontier"\n',
    )
    w(
        "research/hosm/index.md",
        '---\nokf_version: "0.4"\nflip: "0.4"\n---\n# HOSM\n',
    )
    w(
        "research/hosm/references/paper-alpha.md",
        "---\nid: A1\naliases: [A1]\n---\n# Paper Alpha\n",
    )
    w(
        "research/hosm/claims/claim-one.md",
        "---\nid: C1\n---\n# Claim One\n\n"
        "[[A1]] [[front:A1]] [[front#T2]] [[front:T9]] [[nope:A1]]\n",
    )
    w(
        "areas/frontier/index.md",
        '---\nokf_version: "0.4"\nflip_beat: "0.4"\n---\n# Frontier\n',
    )
    w(
        "areas/frontier/references/paper-beta.md",
        "---\nid: A1\naliases: [A1]\n---\n# Paper Beta\n",
    )
    w(
        "areas/frontier/threads/thread-two.md",
        "---\nid: T2\n---\n# Thread Two\n\n[[A1]]\n",
    )
    w("Notes.md", "# Notes\n\n[[hosm:C1]] [[A1]] [[A33]]\n")
    return root


@pytest.fixture()
def flip_vault(tmp_path: Path) -> Path:
    return make_flip_vault(tmp_path)
