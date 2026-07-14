# eno-service

**A FastAPI face on eno's read endpoints — the HTTP surface other tools talk to.**

`eno-service` is the shared, long-running face on an [eno](https://github.com/lavallee/eno)
vault index. Run it once on a host and every tool that speaks HTTP — the
Obsidian plugin, the `eno-mcp` server, sibling projects — queries the same
index instead of each opening its own sqlite handle. Single-host work doesn't
need it; a multi-tool or multi-agent setup does.

## Install

```bash
pip install eno-service
```

Requires Python 3.12+. Pulls in the `enowiki` core (which imports as `eno`).

## Run it

```bash
export ENO_VAULT_DIR=~/vault      # index must already exist — run `eno index` first
eno-serve                         # serves on 127.0.0.1:7891
```

Host and port come from `$ENO_SERVICE_HOST` / `$ENO_SERVICE_PORT` (defaults
`127.0.0.1` and `7891`). Point a client at it with `$ENO_SERVICE_URL`, e.g.
`export ENO_SERVICE_URL=http://localhost:7891`.

## Endpoints

Read (GET):

- `/health` — liveness + configured vault path
- `/search` — notes by title substring or tag
- `/note` — frontmatter + headings + excerpt for one note
- `/neighbors` — backlinks + outbound for one note
- `/orphans` — notes with no inbound links
- `/stubs` — short notes with no outbound links
- `/stale` — notes past a recency threshold
- `/broken-links` — raw broken wikilinks
- `/classify-broken-links` — split into drift (real bugs) vs concepts (groundwork)
- `/frontier` — pages actively reaching outward
- `/hot` — session-start "what's hot" bundle
- `/hygiene` — frontmatter contract audit

Write / compute (POST):

- `/index` — (re)build the index
- `/tiling` — body-content semantic dedup (needs the `enowiki[llm]` extra)
- `/garden` — structural gardener report
- `/hygiene/propose`, `/hygiene/apply` — audit proposals and applies
- `/note/create`, `/note/append` — write notes back with provenance

The service is read-first: `POST /index` and the note-write endpoints are the
mutating exceptions, and every write is human-initiated. Interactive API docs
are served at `/docs` once it's running.

## License

MIT — see [LICENSE](https://github.com/lavallee/eno/blob/main/LICENSE).
