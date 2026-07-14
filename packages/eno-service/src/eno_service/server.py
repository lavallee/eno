"""FastAPI server exposing eno's read endpoints.

Per-request sqlite connection. WAL mode means concurrent reads are fine; the
slight overhead of opening a connection per request is microseconds at vault scale.
The service is read-only in v0 — `POST /index` is the one mutating exception.
"""

import os
from contextlib import contextmanager
from dataclasses import asdict

from eno import garden, hygiene, queries, writes
from eno.config import index_path, vault_dir
from eno.db import open_index
from eno.excerpt import excerpt as build_excerpt
from eno.indexer import index_vault
from eno.views import Proposal
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel


@contextmanager
def _db():
    conn = open_index(index_path(vault_dir()))
    try:
        yield conn
    finally:
        conn.close()


def create_app() -> FastAPI:
    app = FastAPI(title="eno-service", version="0.0.1")

    @app.get("/health")
    def health():
        return {"ok": True, "vault": str(vault_dir())}

    @app.get("/search")
    def search(q: str, kind: str = "title", limit: int = 20):
        try:
            with _db() as db:
                return [asdict(h) for h in queries.search(db, q, kind=kind, limit=limit)]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/note")
    def note(path: str, excerpt: int = 1):
        with _db() as db:
            view = queries.note(db, path)
        if not view:
            raise HTTPException(status_code=404, detail=f"note not found: {path}")
        if excerpt:
            view.excerpt = build_excerpt(vault_dir(), path)
        return asdict(view)

    @app.get("/neighbors")
    def neighbors(path: str):
        with _db() as db:
            n = queries.neighbors(db, path)
        if not n:
            raise HTTPException(status_code=404, detail=f"note not found: {path}")
        return asdict(n)

    @app.get("/orphans")
    def orphans(folder: str | None = None, min_words: int = 0, limit: int = 100):
        with _db() as db:
            return [
                asdict(r)
                for r in queries.orphans(
                    db, folder=folder, min_words=min_words, limit=limit
                )
            ]

    @app.get("/stubs")
    def stubs(max_words: int = 80, limit: int = 100):
        with _db() as db:
            return [
                asdict(r) for r in queries.stubs(db, max_words=max_words, limit=limit)
            ]

    @app.get("/stale")
    def stale(
        older_than_days: int = 180,
        stages: list[str] | None = Query(default=None),
        limit: int = 100,
    ):
        with _db() as db:
            return [
                asdict(r)
                for r in queries.stale(
                    db, older_than_days=older_than_days, stages=stages, limit=limit
                )
            ]

    @app.get("/broken-links")
    def broken_links(limit: int = 200):
        with _db() as db:
            return [asdict(r) for r in queries.broken_links(db, limit=limit)]

    @app.get("/frontier")
    def frontier(
        folder: str | None = None,
        halflife_days: float = 30.0,
        limit: int = 20,
        include_nonpositive: bool = False,
        exclude_types: list[str] | None = Query(default=None),
    ):
        with _db() as db:
            return [
                asdict(r)
                for r in queries.frontier(
                    db,
                    folder=folder,
                    halflife_days=halflife_days,
                    limit=limit,
                    include_nonpositive=include_nonpositive,
                    exclude_types=exclude_types,
                )
            ]

    @app.get("/hot")
    def hot(agent_name: str = ""):
        with _db() as db:
            return asdict(queries.hot(db, agent_name=agent_name))

    class TilingBody(BaseModel):
        threshold: float = 0.80
        error_threshold: float = 0.90
        folder: str | None = None
        min_words: int = 80
        model: str = "nomic-embed-text"

    @app.post("/tiling")
    def tiling_endpoint(body: TilingBody | None = None):
        from eno import tiling as tiling_mod
        body = body or TilingBody()
        with _db() as db:
            return asdict(
                tiling_mod.find_semantic_duplicates(
                    db,
                    vault_dir(),
                    threshold=body.threshold,
                    error_threshold=body.error_threshold,
                    folder=body.folder,
                    min_words=body.min_words,
                    model=body.model,
                )
            )

    @app.get("/classify-broken-links")
    def classify_broken_links_endpoint():
        with _db() as db:
            drift, concepts = garden.classify_broken_links(db)
        return {
            "drift": [asdict(d) for d in drift],
            "concepts": [asdict(c) for c in concepts],
        }

    @app.get("/hygiene")
    def hygiene_endpoint():
        with _db() as db:
            return asdict(queries.hygiene(db))

    @app.post("/index")
    def index(full: bool = False):
        stats = index_vault(vault_dir(), full=full)
        return asdict(stats)

    class ProposeBody(BaseModel):
        include_unknown: bool = False

    @app.post("/hygiene/propose")
    def hygiene_propose(body: ProposeBody | None = None):
        body = body or ProposeBody()
        with _db() as db:
            return asdict(
                hygiene.propose_all(db, include_unknown=body.include_unknown)
            )

    class ProposalIn(BaseModel):
        path: str
        add: dict[str, str]
        confidence: str = "medium"
        reason: str = ""

    class ApplyBody(BaseModel):
        proposals: list[ProposalIn]
        dry_run: bool = False

    @app.post("/hygiene/apply")
    def hygiene_apply(body: ApplyBody):
        proposals = [
            Proposal(
                path=p.path, add=p.add, confidence=p.confidence, reason=p.reason
            )
            for p in body.proposals
        ]
        results = hygiene.apply_all(vault_dir(), proposals, dry_run=body.dry_run)
        return {"results": [asdict(r) for r in results]}

    class GardenBody(BaseModel):
        folder: str | None = None
        resurfacing_min_words: int = 1000
        stub_max_words: int = 80
        stale_days: int = 180
        drift_threshold: float = 0.85
        duplicate_threshold: float = 0.80

    @app.post("/garden")
    def garden_endpoint(body: GardenBody | None = None):
        body = body or GardenBody()
        with _db() as db:
            return asdict(garden.garden(db, **body.model_dump()))

    class CreateBody(BaseModel):
        path: str
        body: str
        frontmatter: dict | None = None
        overwrite: bool = False
        author: str | None = None

    @app.post("/note/create")
    def create_note_endpoint(body: CreateBody):
        result = writes.create_note(
            vault_dir(),
            body.path,
            body.body,
            frontmatter=body.frontmatter,
            overwrite=body.overwrite,
            author=body.author,
        )
        if result.ok:
            index_vault(vault_dir())
            result.indexed = True
        return asdict(result)

    class AppendBody(BaseModel):
        path: str
        content: str
        under_heading: str | None = None

    @app.post("/note/append")
    def append_to_note_endpoint(body: AppendBody):
        result = writes.append_to_note(
            vault_dir(),
            body.path,
            body.content,
            under_heading=body.under_heading,
        )
        if result.ok:
            index_vault(vault_dir())
            result.indexed = True
        return asdict(result)

    return app


def serve(host: str = "127.0.0.1", port: int = 7891) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


def main() -> None:
    """uv-friendly entrypoint reading host/port from env."""
    host = os.environ.get("ENO_SERVICE_HOST", "127.0.0.1")
    port = int(os.environ.get("ENO_SERVICE_PORT", "7891"))
    serve(host=host, port=port)


if __name__ == "__main__":
    main()
