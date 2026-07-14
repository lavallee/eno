# Contributing to eno

eno is a structural intelligence and gardening layer for Obsidian-style
markdown vaults — built for people who keep their knowledge in a pile of
`.md` files and want it to behave like a real, queryable store. Contributions
welcome.

## Dev setup

```bash
git clone https://github.com/lavallee/eno && cd eno
uv sync --all-packages
uv run pytest packages/
uv run ruff check packages/
```

No separate venv bootstrapping, no Docker. The LLM-backed features (`fold`,
`tiling`) need the extra:

```bash
uv sync --all-packages --extra llm
```

## Monorepo layout

- `packages/eno` — the library: indexer, parser, queries, gardening, hygiene,
  and the `eno` CLI. The LLM features (`fold`, `tiling`) live here but import
  `somm` lazily, so the package installs and runs without it.
- `packages/eno-mcp` — MCP stdio server (`eno-mcp`) exposing the read/write
  tools to coding agents.
- `packages/eno-service` — FastAPI face on the read endpoints (`eno-serve`).
- `packages/eno-plugin` — the Obsidian plugin (TypeScript; not a Python
  workspace member).

## Design posture

Three principles shape the code — a change that violates them needs a good
reason in the PR:

1. **Token efficiency is structural.** Index queries return paths + excerpts,
   never whole notes. LLM operations plan over the index first, then read
   targeted.
2. **The vault is the dashboard.** Gardening output is written back as vault
   notes, not surfaced in a bespoke UI.
3. **Resurface, don't enforce.** eno suggests. It never auto-merges,
   auto-deletes, or mutates note bodies without a human in the loop.

## Making a change

1. Write the code and tests. Behavior changes need tests.
2. Add a `CHANGELOG.md` entry under `## [Unreleased]`.
3. If your change touches versioned files, see [`RELEASING.md`](./RELEASING.md)
   — all package versions move in lockstep, never independently.
4. Keep the core LLM-free: anything that needs a model belongs behind the
   `[llm]` extra with a lazy import, never in core `dependencies`.
5. Run the full check before opening a PR:
   ```bash
   uv run ruff check packages/
   uv run pytest packages/
   ```

## Public-repo hygiene

This is a public repository. Keep it free of private paths, personal vault
content, and internal tooling names — example vault content in tests and docs
uses neutral placeholders (`Acme`, `Widget`, …) by design.
