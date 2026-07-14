# enowiki

**Structural intelligence and gardening for your Obsidian vault — the library and `eno` CLI.**

A markdown vault grows into a pile. Notes go orphaned, stubs never get
finished, pages drift into saying the same thing twice, and every "what does
my vault know about X?" costs a full-text grep plus a fat LLM read. `enowiki`
indexes the vault into a queryable surface and gardens it — from the command
line, with no LLM dependency and no model runtime to stand up.

> The PyPI distribution is **`enowiki`** (the bare `eno` was already taken on
> PyPI by an unrelated package). The command, the config vars, and the
> `import eno` module are all just `eno`.

## Install

```bash
pip install enowiki
```

Requires Python 3.12+. The core has no network dependency at all.

## Quickstart

```bash
export ENO_VAULT_DIR=~/vault      # or pass --vault to any command
eno index                         # build the index (writes <vault>/.eno/index.db)
eno hygiene                       # frontmatter contract audit
eno search "mechanism design"     # paths + excerpts, not full notes
```

There is no default vault path — a tool that operates on your notes should
never guess which directory that is. Set `$ENO_VAULT_DIR` or pass `--vault`.
The index lives at `<vault>/.eno/` (override with `$ENO_DIR`). Add `--json` to
any command for machine-readable output.

## What it does

**Retrieve** — `search`, `note`, `neighbors`, `frontier`, `hot`. Graph-aware,
excerpt-first retrieval over frontmatter, wikilinks, tags, and headings.
Queries return paths and small excerpts, not whole notes, so nothing loads
your vault into a prompt.

**Garden & check health** — `orphans`, `stubs`, `stale`, `broken-links`,
`hygiene`, `garden`. The `garden` command writes a dated report back into the
vault (under `9 Vault Health/`) so it's wikilinkable, graph-visible, and
indexable by eno itself. Structural changes always keep a human in the loop —
eno never auto-merges or auto-deletes.

**Write back** — `create-note` and `append-to-note` file notes with provenance
frontmatter (`origin: llm`, an `author` wikilink), so later gardening passes
stay provenance-aware.

## The `[llm]` extra

The LLM-backed features are behind an optional extra and import their model
dependency lazily — the structural core above needs none of it:

```bash
pip install enowiki[llm]
```

- **`eno fold`** — distills a date range or a topic (by wikilink, folder, or
  tag) into a structured, cited rollup note, with supersession metadata and
  fold-of-folds level stacking. Extractive-only, with a count-check that flags
  any numeric claim or citation date not present in the sources.
- **`eno tiling`** — body-content semantic dedup: finds notes that say the same
  thing in different words, in two confidence bands. A signal for human review,
  never an auto-merge.

Both route through [somm](https://github.com/lavallee/somm), which owns
provider selection and is local-first (ollama) by default — vault prose never
has to leave your machine. Call these without the extra installed and you get a
clean `pip install enowiki[llm]` hint, not a crash.

## The rest of the family

`enowiki` is the core of a small workspace. Two sibling packages put the same
index behind other faces:

- **[`eno-mcp`](https://github.com/lavallee/eno/tree/main/packages/eno-mcp)** —
  an MCP stdio server exposing the read/write tools to coding agents.
- **[`eno-service`](https://github.com/lavallee/eno/tree/main/packages/eno-service)** —
  a FastAPI face on the read endpoints, for sibling tools.

See the [project README](https://github.com/lavallee/eno) for the full picture.

## License

MIT — see [LICENSE](https://github.com/lavallee/eno/blob/main/LICENSE).
