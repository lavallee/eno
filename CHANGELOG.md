# Changelog

All notable changes to eno are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and eno adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). All packages in the
workspace move in lockstep.

## [Unreleased]

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

[Unreleased]: https://github.com/lavallee/eno/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lavallee/eno/releases/tag/v0.1.0
