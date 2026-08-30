# Eno minimalist-skill pilot: directional result

This was the initial directional readout. The repeated held-out gate and final
promotion decision are in [`RESULTS-HELDOUT.md`](RESULTS-HELDOUT.md).

Date: 2026-07-29

Decision at this stage: retain the 149-word core as the next candidate; do not promote the
Terra overlay or replace Eno's published onboarding brief yet.

## What was tested

The public 26-note demo vault was copied and freshly indexed for every run. The
three cases covered active-surface retrieval, Eno's concept-versus-drift
distinction, and an append to the canonical existing note. Each write ran
against a disposable vault and was scored against the exact changed-path set.

The published onboarding brief is 882 words. The candidate invariant core is
149 words, an 83% reduction. The experimental Terra overlay adds 34 words, for
a 79% reduction relative to the published brief.

These are single-run directional trials. Forced skill invocation isolates body
efficacy from trigger quality. They do not establish repeatability, implicit
triggering, coexistence, or publication readiness.

## Behavioral readout

The smoke batch was `20260729T211522Z-94341f`; the Terra three-case batch was
`20260729T211755Z-72ab03`. Input-token and duration values are diagnostic, not
stable performance claims.

| Model / case | No skill | Incumbent | Core | Profiled |
| --- | ---: | ---: | ---: | ---: |
| Sol / link semantics | 7/7 | 7/7 | not run | 7/7 |
| Terra / active surface | 6/6 | 6/6 | 6/6 | 6/6 |
| Terra / link semantics | 3/7 | 7/7 | 7/7 | 7/7 |
| Terra / write existing | 7/7 | 7/7 | 7/7 | 7/7 |

The incumbent write score shown as 5/7 in the original Terra batch was a scorer
defect: the expected appended terms were present in the vault diff but the
scorer inspected only the final answer. After the scorer was corrected to score
the final answer plus diff, a clean rerun (`20260729T214120Z-253808`) scored 7/7
and changed only
`2 Research Areas/Synthesis - Spaced Repetition and Active Recall.md`.

The strongest observed need is narrow: Terra with no skill did not call Eno on
the link-semantics case and misreported the temporary work directory as a
missing vault in both directional batches. The invariant core restored the
correct `eno_drift` / `eno_concepts` behavior. Sol handled that case without a
skill, though the 149-word candidate used 103,008 input tokens versus 223,066
for the incumbent in the smoke sample. This is promising efficiency evidence,
not a causal estimate from one run.

The Terra overlay is not earned. Core and profiled arms had identical
correctness on all three cases. `eno_hot` was already induced by the
active-surface task; on link semantics it added a call without a correctness
gain; on the write case it also did not improve safety. Keep the overlay only as
an experimental routing probe until repeated held-out evidence says otherwise.

## Mixed parent / child routing

Batch `20260729T213945Z-d4dfb4` passed the end-to-end mixed gate 7/7 with no
vault changes:

| Session | Requested tuple | Spindle profile | Runtime evidence |
| --- | --- | --- | --- |
| Parent | Codex / Sol / high / reviewer | `codex-sol-reviewer-candidate` | Only the reviewer realization was discoverable in the parent skill root |
| Child | Codex / Terra / medium / explorer | `codex-terra-explorer-candidate` | Child rollout served Terra at medium effort, contained the explorer realization marker, and called `eno_hot`, `eno_drift`, and `eno_concepts` |

This exposed an important adapter boundary. Spindle can independently select
both realizations from one installed package, but Codex 0.146.0 shares its skill
registry across a parent and spawned child. Two same-named realizations cannot
be safely selected with child-local `skills.config` alone. The working pilot
therefore projects the parent realization as a session-local skill and the
child realization through its generated custom-agent developer instructions.
The child rollout, rather than the parent's abbreviated JSON event stream, is
the authoritative receipt for served model, effort, profile marker, and Eno
calls.

## Decision and next gate

Advance the invariant core to a repeated held-out test. Do not advance the
overlay. The next test should add paraphrased tasks unknown to the candidate,
run at least five repeats per consequential arm, and include implicit-trigger
and unrelated-task negatives. Promotion should require:

1. Terra core remains materially better than no skill on Eno-specific semantic
   distinctions and non-inferior to incumbent on write safety.
2. Sol core is non-inferior to no skill while retaining a meaningful instruction
   or execution-cost advantage.
3. Any tuple overlay beats the core on its named gap consistently enough to pay
   for its added surface.
4. Every parent and child receipt records requested and served tuple, source and
   realization digests, selected profile, projection surface, tool trace, and
   exact vault diff.
5. Unknown or requested/served-mismatch tuples fall back to the invariant core,
   and strict mode refuses a tuned claim.

Run the reproducible commands in `PILOT.md`. Raw runtime packages and run
artifacts remain intentionally ignored under `.state/` and `runs/`; sanitized
directional and routing receipts are retained under `evidence/`.
