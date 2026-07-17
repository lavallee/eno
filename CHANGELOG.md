# Changelog

All notable changes to eno are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and eno adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). All packages in the
workspace move in lockstep.

## [Unreleased]

## [0.2.0] — 2026-07-16

### Added

- **flip-bundle awareness** — eno now understands
  [flip](https://github.com/lavallee/flip)'s on-disk conventions, with no
  dependency on the flip package and no behavior change on flip-free vaults:
  - Bundle detection from `index.md` frontmatter (`okf_version` plus `flip` or
    `flip_beat`), with nested bundles resolved by longest path prefix.
  - `.flip/workspace.toml` handle table read at index time (vault-root
    location; handles bound to indexed bundle directories).
  - Wikilink resolution for flip entity references, scoped per bundle: bare
    `[[A3]]` resolves to the entity inside the containing bundle, and
    qualified `[[handle:A3]]` resolves via the workspace handle table. Unknown
    handle or unknown id stays unresolved — never a guess. Literal paths and
    basenames still win first (a real `A3.md` file beats an in-bundle entity).
  - Garden: unresolved id-shaped references on flip vaults are classified as
    `flip_refs` (never concept candidates) with actionable hints — unknown
    handle, unknown id in a known bundle, or bare id written outside any
    bundle.
  - `flip_id`, `bundle_path`, and `bundle_handle` on note views (CLI
    `eno note --json`, `GET /note`, MCP `eno_note`).
  - Flip counters (`flip_bundles`, `flip_handles`, `flip_id_collisions`) in
    index stats.
  - Deliberately deferred: `--bundle` filters on search/frontier (and a
    dedicated MCP flip tool) wait for a later release once real usage shows
    the need.

### Changed

- **Index schema v2.** Existing indexes rebuild automatically on the next
  `eno index` (a one-time full reparse). Note: an `eno-service` instance
  opening a v1 database serves an empty index until it is reindexed
  (`eno index` or `POST /index`).
- Parser records wikilink `#` anchors instead of discarding them.

### Deprecated

- `handle#id` is accepted on read as a synonym for `handle:id`. This applies
  to wikilinks only; prose bracket citations and frontmatter refs are outside
  the link model.

## [0.1.1] — 2026-07-14

Documentation and onboarding. No API, CLI, or schema changes.

### Added

- **`examples/demo-vault`** — a small synthetic Obsidian vault that exercises
  every eno feature (orphans, stubs, drift vs. incipient links, frontier,
  hygiene gaps), so you can `eno --vault examples/demo-vault index` and see real
  signal without pointing eno at your own notes.
- **["How eno works"](https://lavallee.github.io/eno/how-it-works.html)** page on
  the docs site — the index pipeline plus what eno surfaces, as accessible charts
  over the demo vault. Chart forms and colours were chosen with
  [vizier](https://github.com/lavallee/vizier) (horizontal bars for ranked
  magnitudes, divided bars for part-to-whole, colourblind-safe palette,
  AA-validated label ink).
- Per-package READMEs for `enowiki`, `eno-mcp`, and `eno-service`, wired as the
  PyPI `readme` so each project page renders.

### Changed

- Expanded the main README with a two-minute hello-world over the demo vault and
  a fuller CLI tour.

## [0.1.0] — 2026-07-14

First public release.

### Added

- **Structural core (`eno`)** — SQLite index over frontmatter, wikilinks, tags,
  and headings; excerpt-first retrieval (`search`, `note`, `neighbors`,
  `concepts`, `frontier`, `hot`); gardening and health checks (`orphans`,
  `stubs`, `stale`, `broken-links`, `drift`, `hygiene`, `health`). No LLM
  dependency.
- **MCP server (`eno-mcp`)** — stdio server exposing the retrieval and health
  tools to coding agents, plus `eno_create_note` / `eno_append_to_note` for
  writing back with provenance.
- **HTTP service (`eno-service`)** — FastAPI face on the read endpoints for
  sibling tools.
- **Obsidian plugin (`eno-plugin`)** — talks to a running `eno-service`.
- **LLM extra (`enowiki[llm]`)** — `fold` (time-range and topic-driven distillation
  with supersession metadata and fold-of-folds level stacking) and `tiling`
  (body-content semantic dedup), routed through
  [somm](https://github.com/lavallee/somm). Lazily imported: the core installs
  and runs without it.

### Notes

- Vault location is configured via `--vault` or `$ENO_VAULT_DIR`; there is no
  default path.

[Unreleased]: https://github.com/lavallee/eno/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/lavallee/eno/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/lavallee/eno/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lavallee/eno/releases/tag/v0.1.0
