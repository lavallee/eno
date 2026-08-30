# Eno minimalist-skill pilot: held-out gate

Date: 2026-07-30

Decision: promote the revised 145-word invariant core as Eno's Codex runtime
skill; retain the 882-word onboarding brief as separate cross-harness integration
material; ship no Codex-specific overlay.

This report records the Codex gate. A subsequent Claude Sonnet/Opus gate added
an Opus-only overlay to the same package; see `RESULTS-CLAUDE.md`.

## Scope and evidence

Every behavioral trial used a fresh indexed copy of Eno's public 26-note demo
vault and a fresh ephemeral Codex session. Expected answers lived only in the
scorer. The follow-on gate retained 106 trial entries across held-out
paraphrases, identical-prompt stability, write safety, negative controls,
revision regression, production smoke, and a production mixed parent/child
handoff. Raw runs remain local; `evidence/2026-07-30-heldout-summary.json`
retains the sanitized receipt.

The promoted package is 145 words and 970 bytes, versus 882 words and 6,142
bytes for the onboarding brief: an 84% word reduction. Neither Codex profile
selects an overlay. They are empty-delta claims that the invariant core is
sufficient for:

- Codex 0.146.0 / `gpt-5.6-sol` / high / reviewer; and
- Codex 0.146.0 / `gpt-5.6-terra` / medium / explorer.

Both profiles are also pinned to the evaluated Eno MCP toolset digest. A changed
harness build or toolset falls back to the invariant core; strict realization
exits 2 instead of making a tuned claim.

## Held-out generalization

Five independently worded semantic tasks asked for a real link defect and an
intentional unresolved concept without naming Eno's tools or expected answers.

| Model / arm | Full runs | Checks | Median input | Median duration |
| --- | ---: | ---: | ---: | ---: |
| Sol / no skill | 4/5 | 34/35 | 128,287 | 40.290 s |
| Sol / incumbent | 5/5 | 35/35 | 144,168 | 52.335 s |
| Sol / core | 5/5 | 35/35 | 122,633 | 49.746 s |
| Terra / no skill | 5/5 | 35/35 | 120,106 | 28.108 s |
| Terra / incumbent | 5/5 | 35/35 | 112,613 | 29.256 s |
| Terra / core | 5/5 | 35/35 | 97,774 | 27.583 s |

The Sol no-skill miss was method-only: it found and reported the right classes
from raw broken links but skipped `eno_drift` once. The result still matters as
protocol conformance, but it is not an outcome failure.

The core also passed all five held-out prompts implicitly on both models. Sol
used median 140,640 input tokens and Terra 93,460; both called `eno_drift` and
`eno_concepts` in 5/5 sessions. This validates the skill description as a trigger
for these tasks without a `$skill` directive.

## Ambiguity stability

The original, less directive link-cleanup prompt was repeated five times per
Terra arm.

| Arm | Full runs | Checks | Median input | Median duration | Median Eno calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| No skill | 1/5 | 19/35 | 53,289 | 14.604 s | 0 |
| Incumbent | 4/5 | 34/35 | 112,087 | 29.067 s | 6 |
| Core | 5/5 | 35/35 | 79,909 | 21.352 s | 5 |

Four no-skill sessions treated the empty temporary working directory as the
vault and made no Eno call. The core removed that failure mode in 5/5 repeats.
The incumbent's only miss was method-only: it returned acceptable examples but
did not call `eno_concepts`. Relative to incumbent, the core reduced median
input by 29% and median duration by 27% in this batch.

This is the clearest behavioral lift: the core is ambiguity insurance. When a
prompt itself states the complete semantic distinction, current models can often
recover from MCP schemas alone; when the request is underspecified, Terra needs
the small invariant steering surface reliably.

## Write ownership and oversteer

The canonical append case was repeated five times per Terra arm. No skill,
incumbent, and core all scored 5/5, changed only
`2 Research Areas/Synthesis - Spaced Repetition and Active Recall.md`, called
`eno_append_to_note` once per run, and never called `eno_create_note`.

This behavior is largely owned by the Eno tool schema and write API, not the
skill. The first candidate's broad provenance sentence caused inline attribution
comments in 3/5 core runs, even though Eno's convention applies authorship to new
notes. The sentence was narrowed to new-note authorship. The revised core then
passed 5/5 write regressions with zero attribution comments or duplicate notes.

## Trigger negatives

Five unrelated tasks—arithmetic, uppercase conversion, geography, sorting, and
prime identification—ran on both models with no skill and with the core installed
for implicit activation. All 20 sessions passed, made zero Eno calls, and changed
no vault file.

The installed skill added about 107-108 median input tokens, consistent with its
always-visible metadata rather than body activation. This is the observed
ineligible-task activation tax for this harness snapshot.

## Production and mixed-model routing

The promoted package at `packages/eno-mcp/skills/eno-vault` passed six production
smoke sessions: forced Terra semantics, forced Terra write safety, implicit
semantics on both models, and unrelated negatives on both models. The package is
included in the built `eno-mcp` wheel under `eno_mcp/skills/eno-vault`.

Production mixed batch `20260730T001258Z-09d9ca` passed 7/7 with no vault
changes. The Sol/high/reviewer parent saw only its realization. The spawned
Terra/medium/explorer child rollout recorded its own profile ID and realization
digest, then called both `eno_drift` and `eno_concepts`. Because Codex 0.146.0
shares skill discovery across parent and child, the adapter projects the child's
resolved core through its custom-agent developer layer; a profile/digest marker
in the child rollout proves which receipt was applied.

## Essence retained

The evidence supports three retained atoms:

1. Ground vault-dependent claims in Eno and cite note paths; do not substitute
   general knowledge or the empty working directory.
2. Preserve Eno's non-generic concept-versus-drift distinction.
3. Before writing, find the canonical home; create only when none fits, and keep
   authorship explicit on new notes.

Tool inventory, generic examples, unconditional `eno_hot`, overwrite behavior,
and ordinary append mechanics belong to MCP schemas, Eno's deterministic layer,
or the harness—not the runtime skill.

## Promotion boundary

This gate's promotion applies only to the pinned Codex profiles and the invariant
fallback. It does not claim efficacy for another model, Codex build, Eno tool
envelope, private vault, or task distribution. Later harness profiles require
their own evidence; the Claude evidence is recorded separately. The longer
onboarding brief remains available for integrations that do not expose rich MCP
schemas or cannot perform session-local realization.
