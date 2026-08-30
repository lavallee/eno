# Eno minimalist-skill pilot

Status: the revised invariant core passed the held-out gate and was promoted to
`packages/eno-mcp/skills/eno-vault`. Candidate and incumbent copies in this
directory remain experimental fixtures.

## Question

Can current Codex and Claude models preserve Eno-specific behavior with a small
invariant core, activate it without explicit invocation, avoid unrelated tasks,
and route the same installed package from the actual session coordinate?

The published onboarding brief remains the incumbent. The candidate removes
tool inventory already exposed by MCP schemas, generic examples, repeated
procedure, and the session-start rule. Its invariant core retains only:

- vault-grounded claims and two-phase reads;
- the Eno-specific concept-versus-drift distinction; and
- canonical placement and provenance boundaries for writes.

The initial Terra overlay tested a forced `eno_hot` session-start rule. Repeated
trials found no correctness or safety benefit, so the overlay was removed. The
Codex profiles and Claude Sonnet profile record that the invariant core is
sufficient for their exact tuples. Claude Opus alone earned a 12-word overlay
that prevents direct filesystem access to vault content.

One package remains the source of truth. Before each session, Spindle resolves
the package against the actual harness/model/effort/role tuple. The pilot
projects the resulting Sol reviewer into the parent's session-local skill root.
For a spawned Terra explorer, it projects that child's independently resolved
body into the custom-agent developer layer and retains the child rollout as the
served-model receipt. This adapter step is necessary because Codex 0.146.0
builds a session-wide skill registry; a child `skills.config` layer does not
replace a same-named parent skill.

For Claude print-mode trials, the adapter realizes the package for the exact
canonical model reported by Claude, then projects it into a unique project-local
`.claude/skills/` root. For a differently modeled child, it independently
realizes the child tuple and injects that immutable body into the child custom
agent's system prompt. The parent skill stays session-local, and only the child
receives the inline Eno MCP server. This avoids treating Claude's shared skill
discovery surface as if it could hold two same-named realizations at once.

## Arms

| Arm | Loaded instruction surface |
| --- | --- |
| `none` | MCP tool descriptions only |
| `incumbent` | Current full Eno onboarding body in a valid pilot wrapper |
| `core` | Candidate invariant `SKILL.md`, realized through an unmatched control role |
| `profiled` | Candidate realized for the actual model, effort, and agent role |
| `production` | Promoted `eno-vault` package with build/toolset-pinned profiles |

Forced invocation is used in the first behavioral pass so body efficacy is not
confounded with trigger quality. Implicit-trigger and coexistence tests come
only after the body shows value.

## Cases and gates

The public demo vault supplies three scored cases in `cases.json`: active-surface
retrieval, concept-versus-drift triage, and append-to-the-canonical-note. Every
run gets a fresh temporary copy and a fresh index. No personal vault is used.

A profile may advance only if:

1. the incumbent beats no-skill on at least one Eno-specific correctness check;
2. the core is non-inferior to the incumbent on correctness and write safety;
3. an overlay beats core on its exact tuple enough to justify its tokens;
4. the requested and served model, effort, role, skill digest, selected overlay,
   tool calls, token use, and vault diff are retained; and
5. parent and child sessions resolve independently, while unknown and
   requested/served-mismatch cases fall back conservatively.

Directional results are evidence for a larger held-out run, not promotion.

## Running

From the Eno repository:

```bash
uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --matrix smoke --jobs 2

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --case link-semantics --arm profiled --model gpt-5.6-terra

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --matrix terra-directional --jobs 2

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py --mixed

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --matrix heldout --jobs 4

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --matrix stability-terra --jobs 3

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --matrix stability-write-terra --jobs 3

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --matrix production-smoke --jobs 3

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --claude-matrix smoke --jobs 2

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --claude-matrix stability --jobs 2

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --claude-matrix implicit --jobs 2

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --claude-matrix negative --jobs 4

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --claude-matrix opus-overlay --jobs 2

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --claude-matrix production-smoke --jobs 2

uv run python experiments/spindle-minimalist-skill/scripts/run_pilot.py \
  --claude-mixed both --repeats 3 --jobs 2
```

Runtime packages and raw runs are local-only under `.state/` and `runs/`.
See `RESULTS.md` for the directional readout, `RESULTS-HELDOUT.md` for the Codex
gate, and `RESULTS-CLAUDE.md` for the Claude Sonnet/Opus fresh-session and
mixed-model gates.
