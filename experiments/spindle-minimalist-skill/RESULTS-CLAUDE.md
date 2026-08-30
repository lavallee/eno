# Eno minimalist-skill pilot: Claude print-mode gate

Date: 2026-07-30

Decision: promote the invariant core for the pinned Claude Sonnet session and a
12-word Opus-only overlay that keeps vault access on the Eno MCP surface.

## Scope and environment

The gate ran Claude Code 2.1.220 through `claude -p` against exact canonical
model IDs reported by the harness:

- `claude-sonnet-5` / medium effort / explorer role; and
- `claude-opus-5` / high effort / reviewer role.

Each trial used a unique project directory, a freshly indexed copy of Eno's
public 26-note demo vault, a strict temporary MCP configuration, no session
persistence, and `dontAsk` permission mode. The selected realization was linked
into that trial's `.claude/skills/` directory. Claude's init event had to report
the requested model and discover the expected skill; tool calls, permission
denials, costs, model usage, final text, and exact vault diffs were retained.

The promotion set contains 79 valid trial entries. The core, profiled, and
production arms passed 51/51 trials and 301/301 checks. The remaining misses
were confined to no-skill and long-incumbent controls. Raw runs remain local;
`evidence/2026-07-30-claude-summary.json` is the sanitized receipt.

## Repeated semantic comparison

The baseline link-triage task ran once in the smoke batch and three more times
per model and arm. A full pass requires both Eno semantic tools, acceptable
examples from both classes, read-only behavior, and no vault changes.

| Model / arm | Full runs | Checks | Median context tokens | Median cost | Median duration |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sonnet / no skill | 1/4 | 25/28 | 151,503 | $0.168 | 19.0 s |
| Sonnet / incumbent | 4/4 | 28/28 | 160,119 | $0.192 | 17.8 s |
| Sonnet / core | 4/4 | 28/28 | 111,244 | $0.138 | 13.6 s |
| Opus / no skill | 3/4 | 27/28 | 275,772 | $0.423 | 72.7 s |
| Opus / incumbent | 0/4 | 24/28 | 260,949 | $0.359 | 49.6 s |
| Opus / core | 4/4 | 28/28 | 249,856 | $0.393 | 51.6 s |

Every control miss was the same protocol miss: the answer contained acceptable
examples but the run skipped `eno_concepts`. Sonnet's 145-word core was both
more reliable and lighter than the 907-word incumbent in this batch. Opus is
the stronger warning against assuming that more skill text is safer: the long
incumbent repeatedly explored other tools and omitted the one semantic call the
task required, while the core was stable.

This is evidence about this fixture and harness snapshot, not a general claim
that Opus always performs worse with long prompts.

## Implicit activation and negatives

The unchanged core passed all five independently worded semantic prompts on
both models without a slash command: 10/10 trials and 70/70 checks. Claude's
init event discovered `eno-vault` in every run. Sonnet used a median two Eno
calls; Opus used eight.

Five unrelated prompts ran with no skill and with the core installed on both
models. All 20 trials passed, made zero Eno calls, and changed no vault files.
The installed metadata added 76 median context tokens on Sonnet and 81 on Opus
in this negative batch, consistent with skill-description visibility without
body activation.

## The Opus residue

The core produced correct Opus answers, but Opus attempted denied `Read` or
`Bash` access in 7/9 matched semantic/write trials. That is a harness-specific
gap: vault content should remain behind Eno's indexed, provenance-aware tool
surface. The candidate overlay added one sentence:

> Use Eno tools, not filesystem tools, to inspect or search vault content.

The same three repeated semantic tasks, five implicit held-outs, and one write
task were rerun with the profile selected.

| Opus arm | Full runs | Checks | Trials with denied filesystem probes | Median context | Median cost | Median duration | Median Eno calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Core | 9/9 | 63/63 | 7/9 (17 attempts) | 244,818 | $0.383 | 53.0 s | 7 |
| Core + overlay | 9/9 | 63/63 | 0/9 | 148,518 | $0.295 | 39.6 s | 6 |

The overlay preserved correctness while removing the targeted behavior. In
this matched set it also reduced median context by 39%, cost by 23%, and
duration by 25%. Those efficiency deltas are diagnostic rather than stable
price or latency forecasts, but they reinforce rather than merely pay for the
12-word addition.

Sonnet did not earn this overlay. It receives an evaluated empty-delta profile:
the invariant core is its complete realized body.

## Production routing

One installed package now carries four exact profiles. The Claude additions are:

| Session coordinate | Profile | Realization |
| --- | --- | --- |
| Claude 2.1.220 / Sonnet 5 / medium / explorer | `claude-sonnet-explorer-2026-07` | invariant core only |
| Claude 2.1.220 / Opus 5 / high / reviewer | `claude-opus-reviewer-2026-07` | invariant core + Opus vault-access overlay |

Both are pinned to Eno toolset digest
`sha256:040f23cbde0b3981075ea9cf328c0011e93fd4ed60718d0754ac3d6110a70783`.
The production matrix passed 8/8 trials and 48/48 checks across forced
semantics, implicit semantics, unrelated negatives, and canonical writes. Every
run reported the exact served model and expected profile; both models had zero
permission denials and zero Eno tool errors.

An Opus-request/Sonnet-served probe resolved to the invariant core with reason
`requested-served-model-mismatch`; strict mode exited 2 instead of claiming a
tuned profile. This is the required conservative behavior when the actual
session coordinate is not the evaluated one.

## Mixed-model parent/child adapter

A follow-on gate tested one installed package in a single Claude print-mode
session whose parent and child use different models. The adapter independently
realizes both exact tuples. It preloads the parent realization as the main
custom agent's session-local skill, while the child custom agent receives its
own realized body in its system prompt and its own inline Eno MCP server. The
session permission allowlist includes both `Agent` and `mcp__eno__*`; scoping the
server to the child does not by itself authorize that namespace.

| Direction | Parent realization | Child realization | Full runs | Checks | Parent Eno calls | Child Eno calls | Median cost | Median duration |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Opus parent -> Sonnet child | Opus reviewer + overlay | Sonnet explorer core | 3/3 | 54/54 | 0 | 16 | $0.101 | 42.2 s |
| Sonnet parent -> Opus child | Sonnet explorer core | Opus reviewer + overlay | 3/3 | 54/54 | 0 | 27 | $0.192 | 62.8 s |

All 6 trials and 108/108 checks passed with zero permission denials and zero
vault changes. Every run retained the same source-package digest and two
different realization digests. The Opus-only overlay followed the Opus agent,
not its parent/child position.

Configured model names are not accepted as served-model evidence. The receipt
joins the root `Agent` result's `resolvedModel` to forwarded child messages and
requires every child message to report the requested canonical model. Claude
reported the Opus runtime variant as `claude-opus-5[1m]` in the agent result and
`claude-opus-5` in child messages, so the adapter retains the raw value while
canonicalizing its bracketed runtime suffix for comparison.

This six-trial gate is a separate follow-on receipt; it does not rewrite the
historical 79-entry fresh-session promotion set. See
`evidence/2026-07-30-claude-mixed-summary.json`.

## Boundary

These gates validate fresh `claude -p` sessions and one independently realized,
differently modeled child per fresh print-mode session on the two named models.
They do not validate model switches after launch, resumed-child follow-ups,
multiple differently modeled siblings or sibling concurrency in one parent,
nested subagents, another Claude Code build, a changed Eno tool envelope, or a
private vault. Those cases still require independent session/agent realization;
the globally installed package must not be rewritten in place.
