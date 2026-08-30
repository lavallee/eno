# Changelog

All notable changes to eno are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and eno adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). All packages in the
workspace move in lockstep.

## [Unreleased]

### Added

- **Flip-estate indexing** — `eno index --flip-registry PATH` consumes Flip's
  JSONL discovery registry and indexes one visible filesystem copy per stable
  notebook UID beneath a shared project root. Dot-directory/worktree copies
  are ignored, duplicate lineages are deterministically shadowed and recorded
  in `state.json`, UID-less notebooks remain visible for review, and
  repeatable `--include-root` flags compose complete roots such as an Obsidian
  vault alongside the repo-local notebooks.
- **Body-text search** — `eno search --kind text` and MCP `eno_search` use an
  FTS5 title/body index and return the owning Flip bundle path and handle.
- Repo-local `.flip/workspace.toml` tables are resolved in their own scopes, so
  two repositories can safely reuse the same notebook handle.
- `ENO_READ_ONLY=1` makes local MCP write tools refuse mutation while retaining
  the full retrieval surface. Local `eno_health` reports this posture and the
  inspectable estate scope.

### Changed

- **Index schema v4.** Existing indexes rebuild automatically on the next
  `eno index` to populate the disposable full-text index.

## [0.3.0] — 2026-07-28

### Added

- **Generic OKF v0.2 consumer** — eno now reads ordinary
  [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
  bundles, not only flip notebooks, with no new dependency and no behavior
  change on OKF-free vaults:
  - **Markdown links as graph edges.** Standard `[alias](target)` links are
    indexed alongside wikilinks (new `links.kind` column, `'wiki'` or `'md'`),
    recording the target as written, the resolved path, the `#anchor`, the
    alias text, and the source line. External schemes, image links, fenced
    code, and inline code spans are skipped.
  - **Resolution is path arithmetic only.** Relative targets resolve against
    the note's directory; bundle-absolute `/…` targets against the containing
    bundle root (a flip bundle when there is one, else the nearest ancestor
    whose `index.md` carries frontmatter, else the vault root), with `dir/` and
    extensionless fallbacks. No basename, alias, or fuzzy matching — an
    unresolved markdown target is recorded unresolved, never guessed. Wikilink,
    Flip-ID, alias, anchor, and workspace resolution are untouched.
  - **Portable trust fields indexed** per note: `sources` (count, plus a
    conservative unresolved count that never counts external URLs or scope
    descriptors), `generated: {by, at}`, `verified` (a bare mapping is read as
    a one-element list, per OKF §5.2), `status`, `stale_after`. Unknown
    frontmatter — OKF extensions, flip's vocabulary, anything else — is
    preserved and surfaced unchanged. Nothing is ever written back to a note.
  - **Trust/currency summaries** on `note` and `neighbors` (CLI, `GET /note`,
    `GET /neighbors`, MCP `eno_note` / `eno_neighbors`) as one compact line:
    `generated 2026-07-01 by agent-x · verified ×2 (1 human) · stale
    2026-09-23 · sources: 3 (1 unresolved)`. Absent fields say nothing; the
    human tier keys off the `human:` actor prefix. Advisory signals, never
    truth verdicts.
  - **`eno trust`** (and `GET /trust`) — advisory review candidates: a passed
    `stale_after`, a load-bearing concept type (`Claim`, `Finding`) with
    neither `sources` nor `generated`, and content whose change signal
    (`generated.at`, else mtime) postdates its latest verification. Review
    candidates, never rejections — eno enforces no policy it doesn't own.

### Changed

- **Index schema v3.** Existing indexes rebuild automatically on the next
  `eno index` (a one-time full reparse), as at v2.
- `eno index` link counters now include markdown edges. Vaults without
  markdown links (the demo vault included) report exactly the same numbers as
  before.
- Broken markdown links are visible in `broken-links` but are never classified
  as concept or drift candidates: a dangling markdown link is legal OKF
  not-yet-written knowledge, not a wikilink gesture or a typo.
- Graph queries (`neighbors`, `orphans`, `stubs`, `frontier`) count markdown
  edges, so a bundle wired with markdown links has a real graph instead of
  looking like a pile of orphans. The wikilink-semantic surfaces — the
  gardener's concept/drift classification and `fold`'s wikilink heat and topic
  selection — stay wikilink-only.

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

[Unreleased]: https://github.com/lavallee/eno/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/lavallee/eno/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lavallee/eno/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/lavallee/eno/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lavallee/eno/releases/tag/v0.1.0
