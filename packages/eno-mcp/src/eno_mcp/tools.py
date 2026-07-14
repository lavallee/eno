"""MCP tool implementations.

Plain functions — registered with FastMCP in server.py. Docstrings ARE the tool
descriptions the agent sees, so prioritize *when* to use the tool over *how* it
works internally. Returns are jsonable dicts; on failure, return {"error", "hint"}
rather than raising — gives the agent something actionable.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from eno.backend import ServiceBackend, make_backend
from eno.client import ClientError
from eno.config import index_path

_BACKEND_HINT = (
    "set $ENO_SERVICE_URL to a running eno-serve, or $ENO_VAULT_DIR to a vault "
    "path (will use the local .eno/index.db; run `eno index` first)"
)


def _to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, list):
        return [_to_dict(o) for o in obj]
    return obj


def _err(e: Exception, hint: str = _BACKEND_HINT) -> dict[str, Any]:
    return {"error": str(e), "hint": hint}


def eno_search(
    query: str, kind: str = "title", limit: int = 20
) -> dict[str, Any]:
    """Find notes in the vault by title substring or tag exact-match.

    Use this when the user asks about something they "have a note on" or
    when you want to ground a question in what they've already written.
    Cheap — index-only, no llm. Always try this before reading files
    blindly with grep.

    Args:
        query: substring (kind='title') or exact tag (kind='tag').
        kind: 'title' or 'tag'. Default 'title'.
        limit: max results. Default 20.

    Returns:
        {"hits": [{"path", "title", "score", "matched_in"}, ...]} on success;
        {"error": "...", "hint": "..."} on failure.
    """
    try:
        hits = make_backend().search(query, kind=kind, limit=limit)
        return {"hits": [_to_dict(h) for h in hits]}
    except (ClientError, ValueError) as e:
        return _err(e)


def eno_note(path: str, with_excerpt: bool = True) -> dict[str, Any]:
    """Get one note's frontmatter, headings, and a short prose excerpt.

    Use this when the user references a specific note by name, or after
    `eno_search` returns a path you want to peek at. Returns a token-cheap
    summary (~1KB), not the full body — if you need the full file, use
    your Read tool with the returned path.

    Args:
        path: vault-relative path (e.g. "2 Projects/Acme/Widget.md").
        with_excerpt: include ~400 chars of body. Default True.

    Returns:
        {"path", "title", "word_count", "frontmatter", "headings", "excerpt"}
        on success; {"note": null, "hint": "..."} if missing;
        {"error": "...", "hint": "..."} on backend failure.
    """
    try:
        view = make_backend().note(path, with_excerpt=with_excerpt)
        if view is None:
            return {"note": None, "hint": f"no note at {path!r}"}
        return _to_dict(view)
    except ClientError as e:
        return _err(e)


def eno_neighbors(path: str) -> dict[str, Any]:
    """List a note's backlinks (notes pointing TO it) and outbound links
    (notes it points AT) — the local link graph around one node.

    Use this when you want to map context: who else has linked to a topic,
    what concepts cluster around a note, where in the vault a project's
    discussion lives. Two graph hops away = call this twice with different
    paths.

    Args:
        path: vault-relative path of the focal note.

    Returns:
        {"path", "title", "backlinks": [...], "outbound": [...]} where each
        list element is {"path", "title", "word_count"}; or
        {"neighborhood": null, "hint": "..."} if the note doesn't exist.
    """
    try:
        n = make_backend().neighbors(path)
        if n is None:
            return {"neighborhood": None, "hint": f"no note at {path!r}"}
        return _to_dict(n)
    except ClientError as e:
        return _err(e)


def eno_orphans(
    folder: str | None = None, min_words: int = 0, limit: int = 20
) -> dict[str, Any]:
    """Find notes with no inbound links — candidates for resurfacing.

    Use this when planning, gardening, or when the user asks "what have I
    written that I've forgotten about?" The biggest orphans by word count
    are usually the most-buried important work.

    POSTURE: orphans aren't bugs, they're forgotten gold. Resurface, don't
    judge.

    Args:
        folder: filter by folder prefix, e.g. "2 Research Areas".
        min_words: only include notes ≥ this size. Default 0.
        limit: max results. Default 20.

    Returns:
        {"count": N, "orphans": [{"path", "title", "word_count"}, ...]};
        sorted by word_count descending.
    """
    try:
        rows = make_backend().orphans(
            folder=folder, min_words=min_words, limit=limit
        )
        return {"count": len(rows), "orphans": [_to_dict(r) for r in rows]}
    except ClientError as e:
        return _err(e)


def eno_stubs(max_words: int = 80, limit: int = 20) -> dict[str, Any]:
    """Find short notes with no outbound links — abandoned starts that
    might want fleshing out, or duplicates of better notes.

    Use this for gardening passes, or when looking for half-finished
    threads in a topic the user is currently working on.

    Args:
        max_words: word-count ceiling. Default 80.
        limit: max results. Default 20.

    Returns:
        {"count": N, "stubs": [{"path", "title", "word_count"}, ...]}.
    """
    try:
        rows = make_backend().stubs(max_words=max_words, limit=limit)
        return {"count": len(rows), "stubs": [_to_dict(r) for r in rows]}
    except ClientError as e:
        return _err(e)


def eno_stale(
    older_than_days: int = 180,
    stages: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Find notes whose mtime is past a threshold.

    Use this for resurfacing — old notes the user might want to revisit.
    By default excludes notes tagged `stage: reference` or `stage: archived`
    (those are intentionally evergreen). Pass `stages=['draft','active']`
    to narrow further.

    Args:
        older_than_days: cutoff in days. Default 180.
        stages: optional list, e.g. ['draft', 'active'].
        limit: max results. Default 20.

    Returns:
        {"count": N, "stale": [{"path", "title", "word_count"}, ...]}.
    """
    try:
        rows = make_backend().stale(
            older_than_days=older_than_days, stages=stages, limit=limit
        )
        return {"count": len(rows), "stale": [_to_dict(r) for r in rows]}
    except ClientError as e:
        return _err(e)


def eno_broken_links(limit: int = 50) -> dict[str, Any]:
    """List wikilinks whose target doesn't currently resolve to any note.

    IMPORTANT — these are NOT bugs by default. The user deliberately writes
    `[[Some Concept]]` references *before* creating the target note, as
    groundwork for emerging research (incipient links). Backlinks from these
    help connect ideas before pages crystallize.

    The actual bug class is *drift*: a wikilink whose target *almost*
    matches an existing note (em-dash vs hyphen, casing, trailing
    punctuation) and silently doesn't resolve. This raw list mixes both
    incipient and drift; the gardener (step 5) is what classifies them.
    Don't pre-classify yourself, and don't frame these as errors.

    Use this when investigating link integrity, when the user asks about
    "concepts I've gestured at but haven't written," or when looking for
    what to draft next.

    Args:
        limit: max results. Default 50.

    Returns:
        {"count": N, "links": [{"src_path", "target_text", "line_no"}, ...]}.
    """
    try:
        rows = make_backend().broken_links(limit=limit)
        return {"count": len(rows), "links": [_to_dict(r) for r in rows]}
    except ClientError as e:
        return _err(e)


def eno_frontier(
    folder: str | None = None,
    halflife_days: float = 30.0,
    limit: int = 20,
    include_nonpositive: bool = False,
    exclude_types: list[str] | None = None,
) -> dict[str, Any]:
    """List vault frontier pages — where the user is *actively reaching outward*.

    score = (out_degree - in_degree) * exp(-age_days / halflife_days)

    A high score means the page links to many things, is linked to by few,
    and was recently touched. Hub pages (in >> out) and stale pages drop out.
    Compare to `eno_orphans` (in_degree=0, no recency signal) and `eno_stale`
    (recency only, no graph signal). This is the third leg.

    Use this when:
    - The user asks "what am I currently working on / pulling threads on?"
    - You want to ground a planning conversation in active threads, not dead
      ones — frontier pages are where the next note often wants to go.
    - You're feeding the user's gardener / compactor and want priority
      pages for review.

    POSTURE: frontier is a *signal*, not a verdict. A high-score page might
    be a brilliant frontier or a runaway shopping list — the user decides.

    Args:
        folder: filter by folder prefix (e.g. "2 Research Areas").
        halflife_days: recency decay constant. Default 30 (recent month
                       weighted ~1.0; ~6 months → ~0.13; year → ~0.0006).
        limit: cap on returned pages. Default 20.
        include_nonpositive: include pages with score <= 0 (hubs, stale).
                             Default False.
        exclude_types: frontmatter `type:` values to skip
                       (e.g. ['log', 'meta']).

    Returns:
        {"count": N,
         "frontier": [{"path", "title", "word_count", "out_degree",
                       "in_degree", "age_days", "recency_weight",
                       "score"}, ...]}
        sorted by score descending.
    """
    try:
        rows = make_backend().frontier(
            folder=folder,
            halflife_days=halflife_days,
            limit=limit,
            include_nonpositive=include_nonpositive,
            exclude_types=exclude_types,
        )
        return {"count": len(rows), "frontier": [_to_dict(r) for r in rows]}
    except ClientError as e:
        return _err(e)


def eno_hot(agent_name: str = "") -> dict[str, Any]:
    """Session-start "what's hot" bundle, derived live from the index.

    The eno equivalent of claude-obsidian's `wiki/hot.md` — but computed,
    not written. Returns the four signals you most want before reading any
    specific note:

    1. **frontier** — pages with high outward reach, low inbound, recently
       touched. Where the user is *currently pulling threads*.
    2. **recent_appends** — notes whose mtime is within the last 7 days,
       newest first. Active surfaces, regardless of graph shape.
    3. **top_concepts** — incipient wikilinks by mention_count. Themes the
       user has been gesturing at across notes — durable interests.
    4. **agent_recent** — notes the agent itself authored within the last
       14 days (when `agent_name` is provided). Your own contribution
       trail; useful for continuity ("I last drafted X on Y").

    Use this:
    - On session start, before any other tool — establishes recent context
      so you don't ask the user to recap.
    - After context compaction (hook-injected context doesn't survive).
    - When the user asks "what was I working on?" or "what's relevant
      right now?"

    Args:
        agent_name: your own agent name as it appears in `author:`
                    frontmatter (e.g. "Weaver"). Pass to populate
                    `agent_recent`. Reads from $ENO_AGENT_NAME if unset.

    Returns:
        {"generated_at", "agent_name",
         "frontier": [...FrontierNote...],
         "recent_appends": [...NoteRef...],
         "top_concepts": [...ConceptCandidate...],
         "agent_recent": [...NoteRef...]}
    """
    import os
    name = agent_name or os.environ.get("ENO_AGENT_NAME", "")
    try:
        bundle = make_backend().hot(agent_name=name)
        return _to_dict(bundle)
    except ClientError as e:
        return _err(e)


def eno_tiling(
    threshold: float = 0.80,
    error_threshold: float = 0.90,
    folder: str | None = None,
    min_words: int = 80,
    model: str = "nomic-embed-text",
) -> dict[str, Any]:
    """Find candidate body-content duplicates via embedding cosine similarity.

    Complements `eno_drift` (link-target fuzzy matches) and the existing
    title-based duplicate scan in `garden`. This one looks at *bodies*: pairs
    of notes whose semantic content is suspiciously close, regardless of
    whether their titles or wikilinks reveal the overlap.

    Two bands:
    - **error_pairs** (similarity >= 0.90): strong near-duplicate; very likely
      the same idea written twice. Surface to the user for consolidation.
    - **review_pairs** (0.80 <= similarity < 0.90): possible tile overlap;
      worth a glance but the author may have meant for them to be distinct.

    Requires the optional LLM extra; embeddings route through somm, which
    owns provider selection. If no model backend is reachable, the response
    carries a non-null `error` string and empty band lists — surface this to
    the user rather than guessing.

    POSTURE: this is a *signal*, never a verdict. Do not auto-merge. Do
    not call concept candidates or drift candidates "duplicates" — those
    are different bug classes. If a tiling pair surprises you, the right
    move is to read both notes (eno_note) and ask the user.

    Embeddings are cached at `<vault>/.eno/tiling-cache.json`. The cache
    is keyed on sha256(model + body), so model swaps invalidate
    automatically and frontmatter-only edits don't re-embed.

    Args:
        threshold: review-band floor (default 0.80). Lower = more pairs.
        error_threshold: error-band floor (default 0.90).
        folder: optional folder prefix filter.
        min_words: skip notes below this word count (default 80 — short
                   stubs have no useful embedding signal).
        model: ollama embed model name. Cache is per-model.

    Returns:
        {"error_pairs", "review_pairs", "pages_scanned", "pages_embedded",
         "cache_hits", "skipped", "model", "error_threshold",
         "review_threshold", "error"}
    """
    try:
        report = make_backend().tiling(
            threshold=threshold,
            error_threshold=error_threshold,
            folder=folder,
            min_words=min_words,
            model=model,
        )
        return _to_dict(report)
    except ClientError as e:
        return _err(e)


def eno_hygiene() -> dict[str, Any]:
    """Audit the vault's frontmatter contract: which notes lack required
    fields (origin, stage), and how many are missing each field.

    Use this when the user asks about vault structure, before running
    backfill operations, or to gauge how much of the vault is fully
    classified.

    Returns:
        {"counts": {"total", "origin", "stage"},
         "issues": [{"path", "missing": [...]}, ...]};
        the issues list can be long — use `counts` for the headline,
        sample `issues` for examples.
    """
    try:
        rep = make_backend().hygiene()
        return _to_dict(rep)
    except ClientError as e:
        return _err(e)


def eno_concepts(limit: int = 30) -> dict[str, Any]:
    """List concept candidates — wikilink targets the user has gestured
    at but not yet written. Surfaces emergent themes the user is
    thinking about across notes.

    Use this to ground suggestions in what the user actually cares about.
    Instead of asking open-ended "what should I do next?", you can say
    "you've been gesturing at Mechanism Design, Behavioral Economics,
    and Andrej Karpathy across several notes — want to draft notes on
    any of those?"

    POSTURE: these are NOT broken-link errors. They're intentional
    groundwork for notes-not-yet-written. Frame them as opportunities,
    never as bugs to fix.

    Args:
        limit: cap on returned concepts. Default 30 — sorted by
               mention_count descending; the head is the highest-signal.

    Returns:
        {"count": N, "concepts": [{"target_text", "mention_count",
         "sources": [{"src_path", "line_no"}, ...]}, ...]}
    """
    try:
        _, concepts = make_backend().classify_broken_links()
        return {
            "count": len(concepts),
            "concepts": [_to_dict(c) for c in concepts[:limit]],
        }
    except ClientError as e:
        return _err(e)


def eno_drift(limit: int = 20) -> dict[str, Any]:
    """List drift candidates — wikilinks that almost match an existing
    note but don't resolve (em-dash drift, casing, trailing punctuation).

    Use this when investigating link integrity, when the user mentions a
    note and you can't find an exact match by name, or when triaging the
    vault for actionable cleanup. Each candidate names the broken link,
    the suggested existing note it probably meant to point to, and a
    similarity score (0-1, where 1.0 = identical after normalization).

    Args:
        limit: cap on returned candidates. Default 20.

    Returns:
        {"count": N, "drift": [{"target_text", "suggested_path",
         "suggested_title", "score", "sources": [...]}, ...]}
    """
    try:
        drift, _ = make_backend().classify_broken_links()
        return {
            "count": len(drift),
            "drift": [_to_dict(d) for d in drift[:limit]],
        }
    except ClientError as e:
        return _err(e)


def eno_create_note(
    path: str,
    body: str,
    title: str | None = None,
    overwrite: bool = False,
    author: str | None = None,
) -> dict[str, Any]:
    """Create a new note in the vault.

    Use this when filing a skill, summary, or research output you want to
    persist across sessions. The note's frontmatter is auto-populated with
    `origin: llm`, today's `created` and `updated`, and an `author` wikilink
    if provided (or read from $ENO_AGENT_NAME).

    POSTURE: Mark yourself in the `author` field — it's the convention that
    makes future hygiene/garden passes provenance-aware. Don't omit it.

    Args:
        path: vault-relative path. ".md" appended if missing.
        body: prose content. The H1 (matching the title) is added
              automatically; don't include it in body.
        title: explicit frontmatter title. Defaults to filename stem.
        overwrite: if False (default), fail when the note already exists;
              use eno_append_to_note instead. Pass True to replace.
        author: agent identifier for the `author: '[[X]]'` wikilink. Falls
              back to $ENO_AGENT_NAME if not set.

    Returns:
        {"path", "ok", "indexed", "note", "error"} — `indexed: true` means
        the index was refreshed after the write so subsequent eno_search /
        eno_neighbors calls see the new note immediately.
    """
    try:
        backend = make_backend()
        frontmatter = None
        if title is not None:
            frontmatter = {"title": title, "origin": "llm"}
            if author:
                frontmatter["author"] = f"[[{author}]]"
        result = backend.create_note(
            path,
            body,
            frontmatter=frontmatter,
            overwrite=overwrite,
            author=author,
        )
        return _to_dict(result)
    except ClientError as e:
        return _err(e)


def eno_append_to_note(
    path: str,
    content: str,
    under_heading: str | None = None,
) -> dict[str, Any]:
    """Append content to an existing vault note.

    Use this when extending a note you (or a human) already wrote — adding
    a finding to a research dossier, logging a result under a project
    page's "Top items" heading, etc. Prefer this over eno_create_note when
    the note exists.

    Args:
        path: vault-relative path of the existing note.
        content: prose to append. Will be separated from existing content
              by a blank line.
        under_heading: optional. Format e.g. "## State" or "### Open items".
              If provided, content is inserted right under that heading,
              before the next heading at the same or higher level. If
              omitted, content is appended to the end of the file.

    Returns:
        {"path", "ok", "indexed", "note", "error"}.
    """
    try:
        result = make_backend().append_to_note(
            path, content, under_heading=under_heading
        )
        return _to_dict(result)
    except ClientError as e:
        return _err(e)


def eno_health() -> dict[str, Any]:
    """Quick liveness check on the eno backend.

    For ServiceBackend (when $ENO_SERVICE_URL is set), pings /health.
    For LocalBackend, confirms the index file exists. Diagnostic only —
    don't call this before every other tool.

    Returns:
        {"ok", "mode", "vault" | "service_url"}; or {"error", "hint"}.
    """
    try:
        backend = make_backend()
        if isinstance(backend, ServiceBackend):
            res = backend.client.get("/health")
            return res or {"ok": False, "hint": "service returned no body"}
        if not index_path(backend.vault).exists():
            return {
                "ok": False,
                "mode": "local",
                "vault": str(backend.vault),
                "hint": "no index — run `eno index`",
            }
        return {
            "ok": True,
            "mode": "local",
            "vault": str(backend.vault),
            "index": str(index_path(backend.vault)),
        }
    except ClientError as e:
        return _err(e)
