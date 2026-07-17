"""Read backend abstraction.

LocalBackend hits the vault's sqlite index directly — the workstation/dev path.
ServiceBackend hits eno-service over HTTP — the dash-main path and the path
other surfaces (MCP, plugin) take.

`make_backend()` chooses based on env var (ENO_SERVICE_URL) and explicit args,
so the CLI doesn't need a service running for single-host work.
"""

import os
import sqlite3
from pathlib import Path
from typing import Protocol

from . import garden as garden_mod
from . import hygiene as hygiene_mod
from . import queries
from . import writes as writes_mod
from .client import EnoClient
from .config import index_path, vault_dir
from .db import open_index
from .excerpt import excerpt
from .views import (
    ApplyResult,
    BrokenLink,
    ConceptCandidate,
    DriftCandidate,
    DuplicatePair,
    FlipRefCandidate,
    FrontierNote,
    GardenReport,
    HeadingView,
    Hit,
    HotCache,
    HygieneIssue,
    HygieneReport,
    Neighborhood,
    NoteRef,
    NoteView,
    Proposal,
    ProposalReport,
    TilingReport,
    WriteResult,
)


class Backend(Protocol):
    def search(
        self, q: str, *, kind: str = "title", limit: int = 20
    ) -> list[Hit]: ...
    def note(self, path: str, *, with_excerpt: bool = True) -> NoteView | None: ...
    def neighbors(self, path: str) -> Neighborhood | None: ...
    def orphans(
        self, *, folder: str | None = None, min_words: int = 0, limit: int = 100
    ) -> list[NoteRef]: ...
    def stubs(self, *, max_words: int = 80, limit: int = 100) -> list[NoteRef]: ...
    def stale(
        self,
        *,
        older_than_days: int = 180,
        stages: list[str] | None = None,
        limit: int = 100,
    ) -> list[NoteRef]: ...
    def broken_links(self, *, limit: int = 200) -> list[BrokenLink]: ...
    def frontier(
        self,
        *,
        folder: str | None = None,
        halflife_days: float = 30.0,
        limit: int = 20,
        include_nonpositive: bool = False,
        exclude_types: list[str] | None = None,
    ) -> list[FrontierNote]: ...
    def hot(self, *, agent_name: str = "") -> HotCache: ...
    def tiling(
        self,
        *,
        threshold: float = 0.80,
        error_threshold: float = 0.90,
        folder: str | None = None,
        min_words: int = 80,
        model: str = "nomic-embed-text",
    ) -> TilingReport: ...
    def hygiene(self) -> HygieneReport: ...
    def hygiene_propose(
        self, *, include_unknown: bool = False
    ) -> ProposalReport: ...
    def hygiene_apply(
        self, proposals: list[Proposal], *, dry_run: bool = False
    ) -> list[ApplyResult]: ...
    def garden(self, **kwargs) -> GardenReport: ...
    def classify_broken_links(
        self,
    ) -> tuple[list[DriftCandidate], list[ConceptCandidate]]: ...
    def create_note(
        self,
        path: str,
        body: str,
        *,
        frontmatter: dict | None = None,
        overwrite: bool = False,
        author: str | None = None,
    ) -> WriteResult: ...
    def append_to_note(
        self,
        path: str,
        content: str,
        *,
        under_heading: str | None = None,
    ) -> WriteResult: ...


class LocalBackend:
    def __init__(self, vault: Path):
        self.vault = vault
        self._db: sqlite3.Connection | None = None

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = open_index(index_path(self.vault))
        return self._db

    def search(self, q, *, kind="title", limit=20):
        return queries.search(self._conn(), q, kind=kind, limit=limit)

    def note(self, path, *, with_excerpt=True):
        view = queries.note(self._conn(), path)
        if view and with_excerpt:
            view.excerpt = excerpt(self.vault, path)
        return view

    def neighbors(self, path):
        return queries.neighbors(self._conn(), path)

    def orphans(self, **kwargs):
        return queries.orphans(self._conn(), **kwargs)

    def stubs(self, **kwargs):
        return queries.stubs(self._conn(), **kwargs)

    def stale(self, **kwargs):
        return queries.stale(self._conn(), **kwargs)

    def broken_links(self, **kwargs):
        return queries.broken_links(self._conn(), **kwargs)

    def frontier(self, **kwargs):
        return queries.frontier(self._conn(), **kwargs)

    def hot(self, *, agent_name=""):
        return queries.hot(self._conn(), agent_name=agent_name)

    def tiling(self, **kwargs):
        from . import tiling as tiling_mod
        return tiling_mod.find_semantic_duplicates(
            self._conn(), self.vault, **kwargs
        )

    def hygiene(self):
        return queries.hygiene(self._conn())

    def hygiene_propose(self, *, include_unknown=False):
        return hygiene_mod.propose_all(
            self._conn(), include_unknown=include_unknown
        )

    def hygiene_apply(self, proposals, *, dry_run=False):
        return hygiene_mod.apply_all(self.vault, proposals, dry_run=dry_run)

    def garden(self, **kwargs):
        return garden_mod.garden(self._conn(), **kwargs)

    def classify_broken_links(self):
        return garden_mod.classify_broken_links(self._conn())

    def create_note(self, path, body, *, frontmatter=None, overwrite=False, author=None):
        result = writes_mod.create_note(
            self.vault, path, body,
            frontmatter=frontmatter, overwrite=overwrite, author=author,
        )
        if result.ok:
            self._reindex_after_write()
            result.indexed = True
        return result

    def append_to_note(self, path, content, *, under_heading=None):
        result = writes_mod.append_to_note(
            self.vault, path, content, under_heading=under_heading
        )
        if result.ok:
            self._reindex_after_write()
            result.indexed = True
        return result

    def _reindex_after_write(self) -> None:
        # Drop the cached connection so the post-index state is visible to
        # subsequent reads through this backend.
        from .indexer import index_vault
        if self._db is not None:
            self._db.close()
            self._db = None
        index_vault(self.vault)


class ServiceBackend:
    def __init__(self, base_url: str):
        self.client = EnoClient(base_url)

    def search(self, q, *, kind="title", limit=20):
        rows = self.client.get("/search", {"q": q, "kind": kind, "limit": limit})
        return [Hit(**r) for r in (rows or [])]

    def note(self, path, *, with_excerpt=True):
        data = self.client.get(
            "/note", {"path": path, "excerpt": 1 if with_excerpt else 0}
        )
        return _hydrate_note_view(data) if data else None

    def neighbors(self, path):
        data = self.client.get("/neighbors", {"path": path})
        return _hydrate_neighborhood(data) if data else None

    def orphans(self, **kwargs):
        rows = self.client.get("/orphans", kwargs)
        return [NoteRef(**r) for r in (rows or [])]

    def stubs(self, **kwargs):
        rows = self.client.get("/stubs", kwargs)
        return [NoteRef(**r) for r in (rows or [])]

    def stale(self, **kwargs):
        params = dict(kwargs)
        # Service expects repeated `stages` query params; client.get does this via doseq.
        if "stages" in params and params["stages"] is None:
            params.pop("stages")
        rows = self.client.get("/stale", params)
        return [NoteRef(**r) for r in (rows or [])]

    def broken_links(self, **kwargs):
        rows = self.client.get("/broken-links", kwargs)
        return [BrokenLink(**r) for r in (rows or [])]

    def frontier(self, **kwargs):
        params = dict(kwargs)
        if "exclude_types" in params and params["exclude_types"] is None:
            params.pop("exclude_types")
        rows = self.client.get("/frontier", params)
        return [FrontierNote(**r) for r in (rows or [])]

    def hot(self, *, agent_name=""):
        data = self.client.get("/hot", {"agent_name": agent_name})
        return _hydrate_hot_cache(data) if data else HotCache(generated_at="")

    def tiling(self, **kwargs):
        data = self.client.post("/tiling", kwargs)
        return _hydrate_tiling_report(data) if data else TilingReport(
            error="no response from service"
        )

    def hygiene(self):
        data = self.client.get("/hygiene")
        return _hydrate_hygiene(data) if data else HygieneReport()

    def hygiene_propose(self, *, include_unknown=False):
        data = self.client.post(
            "/hygiene/propose", {"include_unknown": include_unknown}
        )
        return _hydrate_proposal_report(data) if data else ProposalReport()

    def hygiene_apply(self, proposals, *, dry_run=False):
        data = self.client.post(
            "/hygiene/apply",
            {
                "proposals": [
                    {
                        "path": p.path,
                        "add": p.add,
                        "confidence": p.confidence,
                        "reason": p.reason,
                    }
                    for p in proposals
                ],
                "dry_run": dry_run,
            },
        )
        if not data:
            return []
        return [ApplyResult(**r) for r in data.get("results", [])]

    def garden(self, **kwargs):
        data = self.client.post("/garden", kwargs)
        return _hydrate_garden_report(data) if data else GardenReport()

    def classify_broken_links(self):
        data = self.client.get("/classify-broken-links")
        if not data:
            return [], []
        drift = [DriftCandidate(**d) for d in data.get("drift", []) or []]
        concepts = [ConceptCandidate(**c) for c in data.get("concepts", []) or []]
        return drift, concepts

    def create_note(self, path, body, *, frontmatter=None, overwrite=False, author=None):
        data = self.client.post(
            "/note/create",
            {
                "path": path,
                "body": body,
                "frontmatter": frontmatter,
                "overwrite": overwrite,
                "author": author,
            },
        )
        return WriteResult(**data) if data else WriteResult(path=path, ok=False, error="no response")

    def append_to_note(self, path, content, *, under_heading=None):
        data = self.client.post(
            "/note/append",
            {"path": path, "content": content, "under_heading": under_heading},
        )
        return WriteResult(**data) if data else WriteResult(path=path, ok=False, error="no response")


def make_backend(
    *, vault: Path | None = None, service_url: str | None = None
) -> Backend:
    """Pick a backend. Explicit args win; else $ENO_SERVICE_URL; else LocalBackend."""
    url = service_url or os.environ.get("ENO_SERVICE_URL")
    if url:
        return ServiceBackend(url)
    return LocalBackend(vault or vault_dir())


def _hydrate_note_view(data: dict) -> NoteView:
    return NoteView(
        path=data["path"],
        title=data["title"],
        word_count=data.get("word_count", 0),
        frontmatter=data.get("frontmatter", {}) or {},
        headings=[HeadingView(**h) for h in data.get("headings", []) or []],
        excerpt=data.get("excerpt"),
        flip_id=data.get("flip_id"),
        bundle_path=data.get("bundle_path"),
        bundle_handle=data.get("bundle_handle"),
    )


def _hydrate_neighborhood(data: dict) -> Neighborhood:
    return Neighborhood(
        path=data["path"],
        title=data["title"],
        backlinks=[NoteRef(**r) for r in data.get("backlinks", []) or []],
        outbound=[NoteRef(**r) for r in data.get("outbound", []) or []],
    )


def _hydrate_tiling_report(data: dict) -> TilingReport:
    return TilingReport(
        error_pairs=[DuplicatePair(**p) for p in data.get("error_pairs", []) or []],
        review_pairs=[DuplicatePair(**p) for p in data.get("review_pairs", []) or []],
        pages_scanned=data.get("pages_scanned", 0),
        pages_embedded=data.get("pages_embedded", 0),
        cache_hits=data.get("cache_hits", 0),
        skipped=data.get("skipped", {}) or {},
        model=data.get("model", ""),
        error_threshold=data.get("error_threshold", 0.90),
        review_threshold=data.get("review_threshold", 0.80),
        error=data.get("error"),
    )


def _hydrate_hot_cache(data: dict) -> HotCache:
    return HotCache(
        generated_at=data.get("generated_at", ""),
        frontier=[FrontierNote(**f) for f in data.get("frontier", []) or []],
        recent_appends=[NoteRef(**r) for r in data.get("recent_appends", []) or []],
        top_concepts=[ConceptCandidate(**c) for c in data.get("top_concepts", []) or []],
        agent_recent=[NoteRef(**r) for r in data.get("agent_recent", []) or []],
        agent_name=data.get("agent_name", ""),
    )


def _hydrate_hygiene(data: dict) -> HygieneReport:
    return HygieneReport(
        issues=[HygieneIssue(**i) for i in data.get("issues", []) or []],
        counts=data.get("counts", {}) or {},
    )


def _hydrate_proposal_report(data: dict) -> ProposalReport:
    return ProposalReport(
        proposals=[Proposal(**p) for p in data.get("proposals", []) or []],
        total_notes=data.get("total_notes", 0),
        eligible=data.get("eligible", 0),
    )


def _hydrate_garden_report(data: dict) -> GardenReport:
    return GardenReport(
        generated_at=data.get("generated_at", ""),
        resurfacing=[NoteRef(**r) for r in data.get("resurfacing", []) or []],
        concepts=[ConceptCandidate(**c) for c in data.get("concepts", []) or []],
        drift=[DriftCandidate(**d) for d in data.get("drift", []) or []],
        stubs=[NoteRef(**s) for s in data.get("stubs", []) or []],
        stale=[NoteRef(**s) for s in data.get("stale", []) or []],
        duplicates=[DuplicatePair(**p) for p in data.get("duplicates", []) or []],
        # .get default keeps payloads from pre-flip services compatible.
        flip_refs=[FlipRefCandidate(**f) for f in data.get("flip_refs", []) or []],
        stats=data.get("stats", {}) or {},
    )
