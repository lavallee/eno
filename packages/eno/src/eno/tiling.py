"""Semantic tiling — body-content duplicate detection via local embeddings.

Complements `garden.find_duplicates` (title-based) with a body-content
similarity axis. Borrowed from claude-obsidian's DragonScale Mechanism 3,
reshaped to live inside eno's package.

Requires the optional LLM extra (`pip install enowiki[llm]`): embeddings route
through `somm.embed()`, which owns provider selection and is local-first by
default. eno itself makes no assumption about a model runtime.

Read-only. Never modifies notes. Never auto-merges. Surfaces candidate
duplicates for human review.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import vault_dir as default_vault_dir
from .views import DuplicatePair, TilingReport


@dataclass
class _CacheEntry:
    path: str
    body_hash: str
    embedding: list[float]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"dim mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _body_hash(body: str, model: str) -> str:
    h = hashlib.sha256()
    h.update(f"model={model}\n".encode())
    h.update(body.encode("utf-8"))
    return h.hexdigest()


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block. Embeddings are over body
    content; frontmatter changes (tag bumps, status flips) shouldn't
    invalidate the cache or perturb similarity scores."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    return text[end + 5 :]


def _load_cache(cache_path: Path, model: str) -> dict[str, _CacheEntry]:
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if data.get("model") != model:
        # Different model = different vector space; don't reuse.
        return {}
    out: dict[str, _CacheEntry] = {}
    for path, entry in (data.get("embeddings") or {}).items():
        emb = entry.get("embedding")
        h = entry.get("hash")
        if isinstance(emb, list) and isinstance(h, str):
            out[path] = _CacheEntry(path=path, body_hash=h, embedding=emb)
    return out


def _save_cache(cache_path: Path, model: str, entries: dict[str, _CacheEntry]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "model": model,
        "embeddings": {
            e.path: {"hash": e.body_hash, "embedding": e.embedding}
            for e in entries.values()
        },
    }
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(cache_path)


def _candidate_pages(
    db: sqlite3.Connection,
    *,
    min_words: int,
    exclude_stages: tuple[str, ...],
    folder: str | None,
) -> list[tuple[str, str]]:
    """Return [(path, title)] eligible for tiling. Filters: meets the word
    floor, isn't in an excluded stage, isn't under .eno/ etc."""
    sql = """
        SELECT path, title FROM notes
        WHERE word_count >= ?
    """
    params: list = [min_words]
    if exclude_stages:
        placeholders = ",".join("?" * len(exclude_stages))
        sql += f" AND (stage IS NULL OR stage NOT IN ({placeholders}))"
        params.extend(exclude_stages)
    if folder:
        sql += " AND path LIKE ?"
        params.append(f"{folder.rstrip('/')}/%")
    sql += " ORDER BY path"
    return [(p, t) for p, t in db.execute(sql, params).fetchall()]


def _read_body(vault: Path, rel: str, *, max_bytes: int) -> str | None:
    """Read a note body. Skip symlinks and vault-root escapes — both
    would let a hostile path POST off-vault content to ollama."""
    p = vault / rel
    if p.is_symlink():
        return None
    try:
        resolved = p.resolve(strict=True)
        resolved.relative_to(vault.resolve())
    except (OSError, ValueError):
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if len(text.encode("utf-8")) > max_bytes:
        return None
    body = _strip_frontmatter(text)
    if not body.strip():
        return None
    return body


def _embed_via_somm(model: str) -> Callable[[str], tuple[list[float], str | None]]:
    """Build a default embed function that calls somm.embed(). Returns a
    closure (text) -> (embedding, error_str). On failure, returns
    ([], "<error string>") so the caller can record skip stats."""
    try:
        from somm import llm  # lazy: only when actually running tiling
    except ImportError as e:
        raise ImportError(
            "eno tiling requires the LLM extra. Install it with:\n"
            "    pip install enowiki[llm]"
        ) from e

    # Silence somm's default stderr alerter — we already aggregate failures
    # into `skipped['embed_error']` and surface them in the TilingReport.
    # The user shouldn't see double-prints of the same 500 from ollama.
    client = llm(project="eno_tiling", on_error=lambda _: None)

    def _fn(text: str) -> tuple[list[float], str | None]:
        result = client.embed(text, workload="vault_tiling", model=model)
        if result.outcome.value == "ok":
            return result.embedding, None
        # Surface the somm error_detail so the caller can write it to skipped[].
        return [], result.error_detail or f"outcome={result.outcome.value}"

    return _fn


def find_semantic_duplicates(
    db: sqlite3.Connection,
    vault: Path | None = None,
    *,
    threshold: float = 0.80,
    error_threshold: float = 0.90,
    embed: Callable[[str], tuple[list[float], str | None]] | None = None,
    cache_path: Path | None = None,
    model: str = "nomic-embed-text",
    min_words: int = 80,
    max_body_bytes: int = 128 * 1024,
    max_embed_chars: int = 5_000,
    exclude_stages: tuple[str, ...] = ("archived",),
    folder: str | None = None,
) -> TilingReport:
    """Compute pairwise embedding similarity and report candidate duplicates.

    Args:
        db: sqlite connection to the eno index.
        vault: vault root for body reads. Defaults to env-resolved vault_dir().
        threshold: review-band floor (default 0.80).
        error_threshold: error-band floor (default 0.90).
        embed: optional injection point for testing — returns
               (embedding, error_str). Defaults to somm.embed routed
               through ollama + nomic-embed-text.
        cache_path: where to persist embeddings. Defaults to
                    `<vault>/.eno/tiling-cache.json`.
        model: embed model name. Cache invalidates on change.
        min_words: word-count floor for candidate pages (default 80 —
                   stubs and snippets have no useful embedding signal).
        max_body_bytes: skip pages whose UTF-8 body exceeds this.
        exclude_stages: stage values to skip (default ('archived',)).
        folder: optional folder prefix filter.

    Returns:
        TilingReport with error/review band pairs and scan statistics.
    """
    vault = vault or default_vault_dir()
    cache_path = cache_path or (vault / ".eno" / "tiling-cache.json")
    embed = embed or _embed_via_somm(model)

    cache = _load_cache(cache_path, model)
    skipped: dict[str, int] = {}

    candidates = _candidate_pages(
        db,
        min_words=min_words,
        exclude_stages=exclude_stages,
        folder=folder,
    )

    titles: dict[str, str] = {p: t for p, t in candidates}
    embeddings: dict[str, list[float]] = {}
    cache_hits = 0
    pages_embedded = 0
    first_error: str | None = None
    consecutive_failures = 0

    for path, _title in candidates:
        body = _read_body(vault, path, max_bytes=max_body_bytes)
        if body is None:
            skipped["read_or_size"] = skipped.get("read_or_size", 0) + 1
            continue
        h = _body_hash(body, model)
        cached = cache.get(path)
        if cached and cached.body_hash == h:
            embeddings[path] = cached.embedding
            cache_hits += 1
            consecutive_failures = 0
            continue
        # Truncate to fit ollama's effective embed context window. nomic-
        # embed-text supports 8K tokens by spec, but ollama defaults to
        # num_ctx=2048 unless the model file overrides — that ~= 8000
        # chars at 4 chars/token. 7000 chars leaves headroom for the
        # tokenizer being less efficient on prose. Keep the head: the
        # first few paragraphs carry the topic signal.
        embed_input = body[:max_embed_chars] if len(body) > max_embed_chars else body
        if len(body) > max_embed_chars:
            skipped["truncated"] = skipped.get("truncated", 0) + 1
        vec, err = embed(embed_input)
        if err is not None or not vec:
            skipped["embed_error"] = skipped.get("embed_error", 0) + 1
            if first_error is None:
                first_error = err or "empty embedding"
            consecutive_failures += 1
            # If we haven't successfully embedded *anything* yet and we've
            # seen multiple failures, it's almost certainly ollama
            # unreachable or the model missing — bail rather than churning
            # through every page. After at least one success, transient
            # per-page failures (oversized inputs, etc.) keep going.
            if pages_embedded == 0 and consecutive_failures >= 3:
                break
            continue
        embeddings[path] = vec
        cache[path] = _CacheEntry(path=path, body_hash=h, embedding=vec)
        pages_embedded += 1
        consecutive_failures = 0

    # Orphan GC: drop cache entries for paths that aren't candidates anymore.
    live = set(titles)
    for stale_path in [p for p in cache if p not in live]:
        cache.pop(stale_path, None)
    _save_cache(cache_path, model, cache)

    if first_error is not None and not embeddings:
        return TilingReport(
            pages_scanned=len(candidates),
            pages_embedded=pages_embedded,
            cache_hits=cache_hits,
            skipped=skipped,
            model=model,
            error_threshold=error_threshold,
            review_threshold=threshold,
            error=first_error,
        )

    paths = sorted(embeddings)
    error_pairs: list[DuplicatePair] = []
    review_pairs: list[DuplicatePair] = []
    for i, path_a in enumerate(paths):
        for path_b in paths[i + 1 :]:
            try:
                sim = _cosine(embeddings[path_a], embeddings[path_b])
            except ValueError:
                continue
            if sim < threshold:
                continue
            pair = DuplicatePair(
                path_a=path_a,
                path_b=path_b,
                title_a=titles.get(path_a, ""),
                title_b=titles.get(path_b, ""),
                score=round(sim, 4),
            )
            if sim >= error_threshold:
                error_pairs.append(pair)
            else:
                review_pairs.append(pair)
    error_pairs.sort(key=lambda p: -p.score)
    review_pairs.sort(key=lambda p: -p.score)

    return TilingReport(
        error_pairs=error_pairs,
        review_pairs=review_pairs,
        pages_scanned=len(candidates),
        pages_embedded=pages_embedded,
        cache_hits=cache_hits,
        skipped=skipped,
        model=model,
        error_threshold=error_threshold,
        review_threshold=threshold,
        # Per-page failures count toward `skipped['embed_error']`. `error`
        # is reserved for the global-failure case (no embeddings at all).
        error=None,
    )
