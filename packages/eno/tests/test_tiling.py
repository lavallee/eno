"""Tests for tiling.find_semantic_duplicates.

Stub embed fn: maps body content → deterministic vector. Lets us verify
the band logic, cache behavior, and skip rules without depending on ollama.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from eno import tiling
from eno.config import index_path
from eno.db import open_index
from eno.indexer import index_vault


def _write(vault: Path, rel: str, content: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _open(vault: Path):
    return open_index(index_path(vault))


def _word_pad(s: str, words: int = 100) -> str:
    """Pad a body so the indexer counts >= word_count words."""
    return s + "\n\n" + (" ".join("filler" for _ in range(words)))


def _vec(*xs: float) -> list[float]:
    return list(xs)


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class _StubEmbed:
    """Deterministic embedder: assigns a unit vector per token of body."""

    def __init__(self, mapping: dict[str, list[float]] | None = None,
                 raise_on: str | None = None):
        # mapping: substring → vector. The first key found in the body wins.
        self.mapping = mapping or {}
        self.raise_on = raise_on
        self.calls = 0

    def __call__(self, text: str) -> tuple[list[float], str | None]:
        self.calls += 1
        if self.raise_on and self.raise_on in text:
            return [], "ollama unreachable (stub)"
        for needle, vec in self.mapping.items():
            if needle in text:
                return list(vec), None
        return [1.0, 0.0, 0.0, 0.0], None


def test_tiling_groups_into_error_and_review_bands(tmp_path):
    # Three near-duplicates and one outsider. Stub vectors:
    # Topic A.1 and A.2 → high similarity (>= 0.95); Topic A.3 close-ish (>= 0.85);
    # B is orthogonal.
    _write(tmp_path, "a1.md", _word_pad("topic-a1 stub here\n"))
    _write(tmp_path, "a2.md", _word_pad("topic-a2 also stub\n"))
    _write(tmp_path, "a3.md", _word_pad("topic-a3 third\n"))
    _write(tmp_path, "b.md", _word_pad("entirely-other content\n"))
    index_vault(tmp_path)
    db = _open(tmp_path)

    embed = _StubEmbed({
        "topic-a1": _norm([1.0, 0.05, 0.0, 0.0]),
        "topic-a2": _norm([1.0, 0.10, 0.0, 0.0]),
        # cos(a1, a3) ≈ 0.886 → review band; cos(a2, a3) similar.
        "topic-a3": _norm([0.85, 0.50, 0.0, 0.0]),
        "entirely-other": _norm([0.0, 0.0, 0.0, 1.0]),
    })

    report = tiling.find_semantic_duplicates(
        db,
        tmp_path,
        embed=embed,
        cache_path=tmp_path / ".eno" / "tiling-cache.json",
        min_words=10,
    )

    assert report.error is None
    assert report.pages_scanned == 4
    assert report.pages_embedded == 4
    # a1↔a2 are very close: should land in error band
    err_keys = {(p.path_a, p.path_b) for p in report.error_pairs}
    assert ("a1.md", "a2.md") in err_keys
    # a1↔a3 and a2↔a3 mid-band: review
    review_keys = {(p.path_a, p.path_b) for p in report.review_pairs}
    assert ("a1.md", "a3.md") in review_keys or ("a2.md", "a3.md") in review_keys
    # b is far from everyone
    all_keys = err_keys | review_keys
    assert all("b.md" not in pair for pair in all_keys)


def test_tiling_cache_avoids_recompute(tmp_path):
    _write(tmp_path, "alpha.md", _word_pad("topic-x\n"))
    _write(tmp_path, "beta.md", _word_pad("topic-y\n"))
    index_vault(tmp_path)
    db = _open(tmp_path)

    embed1 = _StubEmbed({"topic-x": _norm([1.0, 0.0]), "topic-y": _norm([0.0, 1.0])})
    cache = tmp_path / ".eno" / "tiling-cache.json"
    tiling.find_semantic_duplicates(
        db, tmp_path, embed=embed1, cache_path=cache, min_words=10,
    )
    assert embed1.calls == 2

    # Second run: cache should hit; embed not called.
    embed2 = _StubEmbed({"topic-x": _norm([1.0, 0.0]), "topic-y": _norm([0.0, 1.0])})
    report = tiling.find_semantic_duplicates(
        db, tmp_path, embed=embed2, cache_path=cache, min_words=10,
    )
    assert embed2.calls == 0
    assert report.cache_hits == 2
    assert report.pages_embedded == 0


def test_tiling_cache_invalidates_on_body_change(tmp_path):
    _write(tmp_path, "doc.md", _word_pad("topic-original\n"))
    _write(tmp_path, "other.md", _word_pad("filler-other\n"))
    index_vault(tmp_path)
    db = _open(tmp_path)

    embed1 = _StubEmbed({"topic-original": _norm([1.0, 0.0]), "filler-other": _norm([0.0, 1.0])})
    cache = tmp_path / ".eno" / "tiling-cache.json"
    tiling.find_semantic_duplicates(db, tmp_path, embed=embed1, cache_path=cache, min_words=10)

    # Body changes — same path, new content, new hash.
    _write(tmp_path, "doc.md", _word_pad("topic-CHANGED\n"))
    index_vault(tmp_path)

    embed2 = _StubEmbed({"topic-CHANGED": _norm([0.5, 0.5]), "filler-other": _norm([0.0, 1.0])})
    report = tiling.find_semantic_duplicates(db, tmp_path, embed=embed2, cache_path=cache, min_words=10)
    assert embed2.calls == 1  # only the changed one re-embedded
    assert report.cache_hits == 1


def test_tiling_cache_invalidates_on_model_change(tmp_path):
    _write(tmp_path, "x.md", _word_pad("body-x\n"))
    index_vault(tmp_path)
    db = _open(tmp_path)
    cache = tmp_path / ".eno" / "tiling-cache.json"

    e1 = _StubEmbed({"body-x": _norm([1.0, 0.0])})
    tiling.find_semantic_duplicates(
        db, tmp_path, embed=e1, cache_path=cache, model="nomic-embed-text", min_words=10,
    )
    assert e1.calls == 1

    # Different model: cache invalidates wholesale (different vector space).
    e2 = _StubEmbed({"body-x": _norm([0.0, 1.0])})
    report = tiling.find_semantic_duplicates(
        db, tmp_path, embed=e2, cache_path=cache, model="all-minilm", min_words=10,
    )
    assert e2.calls == 1
    assert report.cache_hits == 0


def test_tiling_skips_short_notes(tmp_path):
    _write(tmp_path, "tiny.md", "# Tiny\n\nshort.\n")
    _write(tmp_path, "longA.md", _word_pad("topic-a\n"))
    _write(tmp_path, "longB.md", _word_pad("topic-a\n"))
    index_vault(tmp_path)
    db = _open(tmp_path)

    embed = _StubEmbed({"topic-a": _norm([1.0, 0.0])})
    report = tiling.find_semantic_duplicates(
        db, tmp_path, embed=embed, cache_path=tmp_path / ".eno" / "c.json",
        min_words=80,
    )
    assert report.pages_scanned == 2  # tiny excluded by min_words
    paths_seen = {p for pair in report.error_pairs + report.review_pairs for p in (pair.path_a, pair.path_b)}
    assert "tiny.md" not in paths_seen


def test_tiling_skips_archived_stage(tmp_path):
    _write(tmp_path, "live.md", "---\nstage: active\n---\n" + _word_pad("topic-a\n"))
    _write(tmp_path, "archive.md", "---\nstage: archived\n---\n" + _word_pad("topic-a\n"))
    _write(tmp_path, "match.md", _word_pad("topic-a\n"))
    index_vault(tmp_path)
    db = _open(tmp_path)

    embed = _StubEmbed({"topic-a": _norm([1.0, 0.0])})
    report = tiling.find_semantic_duplicates(
        db, tmp_path, embed=embed, cache_path=tmp_path / ".eno" / "c.json",
        min_words=10,
    )
    paths_seen = {p for pair in report.error_pairs + report.review_pairs for p in (pair.path_a, pair.path_b)}
    assert "archive.md" not in paths_seen
    assert "live.md" in paths_seen
    assert "match.md" in paths_seen


def test_tiling_returns_clean_error_when_embed_fails(tmp_path):
    _write(tmp_path, "a.md", _word_pad("topic-a\n"))
    _write(tmp_path, "b.md", _word_pad("topic-b\n"))
    index_vault(tmp_path)
    db = _open(tmp_path)

    embed = _StubEmbed(raise_on="topic-")  # every call fails

    report = tiling.find_semantic_duplicates(
        db, tmp_path, embed=embed, cache_path=tmp_path / ".eno" / "c.json",
        min_words=10,
    )
    assert report.error is not None
    assert "ollama unreachable" in report.error
    assert report.error_pairs == []
    assert report.review_pairs == []
    assert report.skipped.get("embed_error", 0) >= 1


def test_tiling_strips_frontmatter_for_hashing(tmp_path):
    """Frontmatter-only edits don't trigger re-embedding."""
    body = _word_pad("topic-stable\n")
    _write(tmp_path, "doc.md", "---\nstage: active\n---\n" + body)
    _write(tmp_path, "other.md", _word_pad("topic-other\n"))
    index_vault(tmp_path)
    db = _open(tmp_path)
    cache = tmp_path / ".eno" / "tiling-cache.json"

    embed1 = _StubEmbed({"topic-stable": _norm([1.0, 0.0]), "topic-other": _norm([0.0, 1.0])})
    tiling.find_semantic_duplicates(db, tmp_path, embed=embed1, cache_path=cache, min_words=10)
    assert embed1.calls == 2

    # Edit only frontmatter; body unchanged.
    _write(tmp_path, "doc.md", "---\nstage: reference\n---\n" + body)
    index_vault(tmp_path)

    embed2 = _StubEmbed({"topic-stable": _norm([1.0, 0.0]), "topic-other": _norm([0.0, 1.0])})
    report = tiling.find_semantic_duplicates(db, tmp_path, embed=embed2, cache_path=cache, min_words=10)
    assert embed2.calls == 0
    assert report.cache_hits == 2


def test_tiling_skips_symlinks(tmp_path):
    _write(tmp_path, "real.md", _word_pad("topic-z\n"))
    real = tmp_path / "real.md"
    link = tmp_path / "link.md"
    if not link.exists():
        os.symlink(real, link)
    index_vault(tmp_path)
    db = _open(tmp_path)

    embed = _StubEmbed({"topic-z": _norm([1.0, 0.0])})
    report = tiling.find_semantic_duplicates(
        db, tmp_path, embed=embed, cache_path=tmp_path / ".eno" / "c.json",
        min_words=10,
    )
    skipped_total = sum(report.skipped.values())
    # link.md gets indexed (it's a .md file) but tiling refuses to read it.
    assert skipped_total >= 1
