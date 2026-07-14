# eno

**Structural intelligence and gardening for your Obsidian vault.**

A markdown vault grows into a pile. Notes go orphaned, stubs never get
finished, pages drift into saying the same thing twice, and every "what does
my vault know about X?" costs a full-text grep plus a fat LLM read. eno indexes
the vault into a queryable surface, gardens it, and exposes it — to you on the
command line, to coding agents over MCP, and to sibling tools over a local HTTP
service.

The core is deliberately light: `pip install enowiki` gives you the whole
structural and gardening surface with **no LLM dependency** and no model
runtime to stand up. The optional `enowiki[llm]` extra adds local-first
distillation and semantic dedup.

> The PyPI package is **`enowiki`** (the bare `eno` was already taken). The
> command, the config vars, and the `import eno` module are all just `eno`.

📊 **[See how it works →](https://lavallee.github.io/eno/how-it-works.html)** —
the pipeline, and what eno surfaces, shown as charts over the demo vault below.

## Two-minute hello world

No vault of your own to point at yet? The repo ships a small synthetic vault so
you can watch everything work in under a minute:

```console
$ pip install enowiki
$ git clone https://github.com/lavallee/eno && cd eno

$ eno --vault examples/demo-vault index
indexed 26 of 26 notes — 47 links resolved, 26 broken in 0.02s

$ eno --vault examples/demo-vault hygiene
hygiene: 6 of 26 notes have issues
  missing origin: 4
  missing stage: 5

$ eno --vault examples/demo-vault orphans --min-words 200
  2 Research Areas/The Forgetting Curve and Memory Consolidation.md  [The Forgetting Curve …]  (852 words)
  2 Research Areas/Information Foraging Theory.md  [Information Foraging Theory]  (582 words)
  2 Research Areas/Attention Residue and Context Switching.md  [Attention Residue …]  (445 words)

$ eno --vault examples/demo-vault frontier
   11.76  out=14  in=1   age=  3d   2 Research Areas/Map of Content - Learning.md
    7.88  out=10  in=1   age=  4d   2 Projects/Building a Research Workflow.md
    3.27  out=5   in=1   age=  6d   2 Projects/Learning in Public.md
```

Point it at your own vault with `--vault ~/notes`, or set `ENO_VAULT_DIR` once
and drop the flag:

```bash
export ENO_VAULT_DIR=~/notes
eno index && eno hygiene
```

## Why eno

- **Token-efficient by construction.** Index queries return paths and small
  excerpts, not whole notes. LLM operations are two-phase: cheap planning over
  the index, then targeted reads. Nothing loads your whole vault into a prompt.
- **The vault is its own dashboard.** Gardening reports are written back into
  the vault as notes (under `9 Vault Health/`), so they're wikilinkable,
  graph-visible, and indexable by eno itself. No separate UI for things
  markdown already shows well.
- **Resurfacing over collecting.** eno surfaces the forgotten, suggests rather
  than enforces, and treats vault content as soft authority. Every structural
  change keeps a human in the loop — it never auto-merges or auto-deletes.
- **Local-first, no phone-home.** The core has no network dependency at all.
  The LLM extra routes through [somm](https://github.com/lavallee/somm), which
  is local-first (ollama) by default; vault prose never has to leave your
  machine.

## Four surfaces, one index

| Package | What it is | Install |
| --- | --- | --- |
| [`enowiki`](packages/eno) | The library + `eno` CLI: index, retrieve, garden, hygiene | `pip install enowiki` |
| [`eno-mcp`](packages/eno-mcp) | MCP stdio server exposing the read/write tools to coding agents | `pip install eno-mcp` |
| [`eno-service`](packages/eno-service) | FastAPI face on the read endpoints, for sibling tools | `pip install eno-service` |
| [`eno-plugin`](packages/eno-plugin) | Obsidian plugin talking to a running `eno-service` | (from source) |

## A tour of what it does

**Retrieve** — excerpt-first, graph-aware. `search` (title/tag), `note`
(frontmatter + headings + a ~400-char excerpt), `neighbors` (backlinks +
outbound), `concepts`, `frontier`, `hot`.

```console
$ eno --vault examples/demo-vault search recall
  5 Tools and Techniques/Active Recall.md  [Active Recall]
  2 Research Areas/Synthesis - Spaced Repetition and Active Recall.md  [Synthesis …]
```

**Garden & check health** — `orphans`, `stubs`, `stale`, `broken-links`,
`hygiene`, `health`, plus a `garden` pass that writes a dated report into
`9 Vault Health/`. The interesting distinction is **drift vs. incipient links**:
a `[[Concept]]` written before its note exists is deliberate groundwork, not a
bug; the real bug is a link that *almost* resolves (`[[Systems  Thinking]]` with
a stray space). eno's `garden` report separates the two — in the demo vault, 23
intentional concept-seeds from 3 genuine near-misses.

**For coding agents (MCP)** — a stdio server gives any MCP client (Claude Code,
Cursor, Windsurf, …) a structural view of the vault: the retrieval and health
tools above, plus `eno_create_note` / `eno_append_to_note` for writing back
with provenance. The intelligence here is the *calling* agent — no model setup
of eno's own required. See the
[`eno-mcp` README](packages/eno-mcp/README.md) for the config and the agent
onboarding skill.

**Serve it** — `eno-serve` puts the read endpoints behind FastAPI so several
tools (and the Obsidian plugin) can share one index on a host. See the
[`eno-service` README](packages/eno-service/README.md).

### With the LLM extra (`pip install enowiki[llm]`)

**`eno fold`** — distills a date range or a topic (by wikilink, folder, or tag)
into a structured, cited rollup note, with supersession metadata and
fold-of-folds level stacking. Extractive-only, with a count-check that flags
any numeric claim or citation date not present in the sources.

**`eno tiling`** — body-content semantic dedup: finds notes that say the same
thing in different words, in two confidence bands. A signal for human review,
never an auto-merge.

Both route through [somm](https://github.com/lavallee/somm), which owns
provider selection and is local-first by default. eno itself makes no
assumption about a model runtime — call these without the extra installed and
you get a clean `pip install enowiki[llm]` hint, not a crash.

## Configuration

eno needs to know where your vault is. In precedence order:

1. `--vault PATH` on any command
2. `$ENO_VAULT_DIR`

There is no default — a tool that operates on your notes should never guess
which directory that is. The index lives at `<vault>/.eno/` (override with
`$ENO_DIR`).

## Documentation

- **[How eno works](https://lavallee.github.io/eno/how-it-works.html)** — the
  pipeline plus what eno surfaces, as accessible charts over the demo vault.
- **[`examples/demo-vault`](examples/demo-vault)** — the shipped synthetic vault
  used throughout these docs; safe to index and experiment on.
- **[MCP setup](packages/eno-mcp/README.md)** — wiring eno into a coding agent.
- **[CONTRIBUTING](CONTRIBUTING.md)** · **[CHANGELOG](CHANGELOG.md)** ·
  **[RELEASING](RELEASING.md)**.

## Status

**Stable core, active development.** The structural core, MCP server, and HTTP
service are used daily over a ~1k-note vault. The Obsidian plugin is functional
but the least battle-tested surface. Semantic embeddings are intentionally
deferred to the `[llm]` extra rather than baked into the core.

Requires Python 3.12+.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The short
version: `uv sync --all-packages`, then `uv run pytest packages/` and
`uv run ruff check packages/`. Anything that needs a model belongs behind the
`[llm]` extra with a lazy import, never in the core dependencies.

## License

MIT — see [LICENSE](LICENSE).
