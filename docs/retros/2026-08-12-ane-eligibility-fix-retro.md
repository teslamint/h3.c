# Retro: ANE eligibility fix

- Date: 2026-08-12
- Source: local merge `47bd2c5`
- Spec: `docs/specs/2026-08-12-ane-eligibility-fix-design.md`
- Plan: `docs/plans/2026-08-12-001-feat-ane-eligibility-fix-plan.md`

## Release data

| Metric | Value |
|---|---|
| **Changed non-test lines** | 3,976 (3,491 added + 485 removed); excludes paths matching `tests/`, `.release-loop/`, `docs/evidence/`, and test-named files |
| Commits | 44 feature commits before merge |
| Review rounds | At least 21 independent verdict checkpoints (ledger lower bound; exact count unavailable) |
| Comments (fixed / deferred) | Not reliably reconstructible / not reliably reconstructible; frontmatter counters were not maintained |
| CI failures | 0 remote CI attempts; local actual-Metal merged-tree verification was used |
| Duration (first spec commit → merge) | 12 hours 59 minutes |
| Units planned / completed | 5 / 5 |

## Success criteria: measured vs declared

| # | Declared criterion | Measurement (command / rubric) | Measured result | Verdict |
|---|---|---|---|---|
| 1 | Every writable qualification failure is structured, publication failure reaches stderr, and failures publish no receipt. | `make h3_ane_tool_tests && python3 -m unittest discover -s tests -p 'test_ane_tools.py'` | verified: merged commit `47bd2c5` passed the retained combined suite; 76 Python tests ran with one pinned-only skip that passed separately, and publication/receipt fixtures remained green (`.release-loop/evidence/retro-merged-suite.json`) | Met |
| 2 | The pinned package/compiler/production-runtime gate rejects stale metadata and accepts canonical metadata. | `make h3_ane_integration_test` | verified: exact merged-tree command exited 2 at `setup/unsafe_work_directory` because the legacy default work directory lacks the current ownership marker; a fresh isolated override passed canonical production loading (`.release-loop/evidence/retro-default-integration.json`) | Not met — the implementation path works, but the declared default command is not rerunnable with existing legacy work state |
| 3 | The produced candidate reports exactly 441 total and 149 Neural-Engine-supported nonconstant operations with zero CPU-only or unknown nonconstant operations. | `H3_ANE_TRACE=1 make h3_ane_integration_test` | verified: exact traced default command exited 2 at the same ownership gate before inventory; an isolated override reported `441/149/149/0` (`.release-loop/evidence/retro-default-integration.json`) | Not met — isolated eligibility is proven, but the declared exact command does not reach the measurement |
| 4 | The real fixed FL2VA candidate passes strict Metal/Core ML parity and publishes one matching receipt. | `export H3_ANE_MODEL=/private/tmp/h3-ane-retro-real-1786545716/visual-block.mlmodelc; ./h3_ane_qualification --model MiniMax-H3/FL2VA/video_vae/source --coreml-model "$H3_ANE_MODEL" --output .release-loop/evidence/ane-qualification.json` | verified: direct merged-tree qualification exited 1 at `parity/parity_bounds_failed`; `max_abs=0.19216197729110718`, `relative_l2=0.038400878187031535`, and `receipt_path:null` (`.release-loop/evidence/retro-default-integration.json`) | Not met — strict numerical parity and authority remain blocked |
| 5 | Default-off execution and every unavailable/error path adopt unchanged Metal output with stable fallback accounting. | `make h3_ane_tests && ./h3_ane_tests` plus merged `make test` | verified: actual-Metal ANE suite passed, full suite reported 1,768 checks, and injected bridge/runtime failures retained Metal fallback (`.release-loop/evidence/retro-merged-suite.json`) | Met |

The release delivers actionable diagnostics, a bounded 441-operation production
collector, an eligible fixed graph, link-safe authority preflights, and a
non-authorizing shadow measurement path. It does not deliver strict numerical
qualification, a receipt, observed Neural Engine placement, or acceleration.

## Carry-forward from previous retro

| Item | Status | Evidence |
|---|---|---|
| Add stage-specific qualification failure diagnostics | Done | `ROADMAP.md` gate 1; structured and actual-bridge tests through `1c98c9d` (T1) |
| Obtain a passing fixed-block qualification receipt | In progress — blocked | Fresh direct qualification is `parity_bounds_failed` with no receipt (`.release-loop/evidence/retro-default-integration.json`) (T1, T2) |
| Retain observed Neural Engine placement evidence | Not started | `ROADMAP.md` gate 3 remains blocked; shadow eligibility is not placement (T2, T8) |
| Measure latency, RSS, and energy in order | Not started | `ROADMAP.md` gates 4–6 remain blocked behind strict qualification and placement (T8) |
| Add a one-command package-to-receipt integration gate | In progress — reopened | Isolated package/compiler/runtime flow passes, but the exact default command fails on legacy work state; `ROADMAP.md` gate 7 tracks closure (T1, Phase 3 criteria 2–3) |

- Previous doc shape: conformant

## Interview Transcript

- Independence level: same-model fresh-context
- Rounds used: 5 (max 5)

| ID | Round | Phase | Probe | Answer | Evidence | Verdict (verbatim) |
|---|---:|---:|---|---|---|---|
| T1 | 1→3 | 4 | Which previous carry-forwards closed or changed form? | Diagnostics closed; strict receipt is blocked; placement/performance are not started; the one-command gate is functionally proven but operationally reopened. | Previous retro; `ROADMAP.md`; U4 evidence; merged measurements | Accepted: the revised answer correctly closes gate 1, reopens gate 7 as functionally proven but operationally incomplete, classifies gate 2 as blocked without authority, and leaves gates 3–6 not started. The new ROADMAP item must be written before calling it tracked. |
| T2 | 1→2 | 5 | How should strict failure and shadow success be described? | Safe default-off diagnostic/measurement PoC only; strict fails `.002/.02`, while shadow passes `.25/.05` with no authority or receipt and Metal output remains authoritative. | Strict spec; shadow deviation; U4 real/shadow evidence | Accepted: the answer correctly separates strict qualification, non-authorizing shadow measurement, anticipated eligibility, observed placement, and production acceleration, with the required metrics and authority fields. |
| T3 | 1→4 | 5 | What is the truthful review/rework count? | At least 21 ledger-visible reviewer verdict checkpoints; exact count and comment totals are unavailable because counters were not maintained. | `.release-loop/progress.md`; release metrics | Accepted: 21 is a defensible ledger-only lower bound under the stated counting method; the answer properly marks exact checkpoint and comment counts unavailable, while the 44-commit and 3,491-added/485-removed metrics reproduce under the declared exclusions. |
| T4 | 1→2 | 5 | Why was review rework high? | Local diagnostic/deadline/authority defects combined with newly discovered parity and revocability boundaries; assertion-only mutation evidence added a separate process failure. | Plan matrix; progress review history; corrective commit chains | Accepted: the answer distinguishes implementation defects from newly discovered authority and numeric-contract boundaries, ties both classes to the corrective commit chains, and recognizes assertion-only mutation evidence as a separate process failure. |
| T5 | 1→4 | 5 | What proves receipt preflight safety across TOCTOU? | Capability failure, post-capability invalidation failure, and committed invalidation are distinct tested states with exact strict/shadow fixtures and merged execution evidence. | `0ca5850`, `b2275a0`, `fe14e88`, `2a43e5d`; manifest; merged suite | Accepted: the answer now distinguishes all three preflight/invalidation branches, names the exact strict, TOCTOU, signal, and coordinator fixtures with correct introduction commits, and binds their current merged-tree execution to the retained full-suite artifact. |
| T6 | 1→4 | 5 | Does mutation evidence execute every mechanism? | Historical U1 records remain source-bound and map receipt/result/adoption transitions; current U4 v2 records execute conversion, compile, summary failure, cancellation, compensation, and rerun; merged suites revalidate current fixtures. | U1/U4 evidence; `retro-merged-suite.json` | Accepted: historical U1 evidence remains honestly source-bound, each transition’s mechanism and rerun are explicit, current merged fixtures are revalidated by `retro-merged-suite.json`, and the later U4 changes are correctly limited to diagnostics and provenance rather than mutation mechanisms. |
| T7 | 1→5 | 3 | Which declared commands ran verbatim on the merged tree? | Exact build/tool/fallback commands passed; exact default integration commands failed on legacy state; direct strict qualification failed parity/no receipt. | `retro-merged-suite.json`; `retro-default-integration.json` | no evidenced answer (dispatch cap): Rejected: criterion 3 now has valid exact-command evidence, but the retained criterion-4 command does not safely bind `H3_ANE_MODEL` as written. In `H3_ANE_MODEL=/path command --coreml-model "$H3_ANE_MODEL"`, shell argument expansion occurs before the temporary assignment, so the recorded command depends on an unstated pre-existing environment value. Retain the literal model path in `--coreml-model`, or record a preceding assignment/export as a separate command. Then C1 Met, C2 Not Met, C3 Not Met, C4 Not Met, and C5 Met are auditable. |
| T8 | 1→2 | 4 | What remains blocked and what evidence unblocks it? | Strict receipt, then observed Instruments placement, then paired latency/RSS/energy; broader blocks and default-on remain later work. | `ROADMAP.md`; plan deferred work; shadow deviation | Accepted: the answer gives the correct sequential unblock evidence for gates 2–6, preserves the broader-block/default-on restriction, and does not allow shadow success to satisfy a claim gate. |
| T9 | 1→2 | 5 | What reusable process rule prevents recurrence? | Execute the exact published default command and every mutation mechanism on merged state, including legacy pre-state; substitutes or assertion-only evidence stop the gate. | Current review rework; U4 v2 evidence; merged measurements | Accepted: the lesson is enforceable and complete because it defines a trigger, required per-transition and post-merge artifacts, and a hard stop condition covering exact default commands, failure mechanisms, and legacy state. |

## Findings

### What worked well

- **What happened**: The final implementation distinguishes contract, receipt,
  load, compute-plan, eligibility, bridge, parity, and publication failures and
  keeps Metal authoritative on every unavailable path.
  **Why**: Actual bridge fixtures and immutable first-failure diagnostics
  replaced the generic backend-unavailable result.
  **How to apply**: Require boundary-specific structured diagnostics before
  optimizing or benchmarking any optional accelerator backend.
  **Cites**: T1, T4, Phase 3 criteria 1 and 5
- **What happened**: Receipt authority stayed link-safe and truthful across
  preflight failure, post-preflight TOCTOU failure, signals, and successful
  invalidation.
  **Why**: The workflow modeled capability and invalidation as separate
  transitions rather than treating a successful preflight as authority removal.
  **How to apply**: Preserve explicit not-started/unchanged and
  started/invalidated states in every authority-bearing measurement workflow.
  **Cites**: T5, Phase 3 criterion 1

### What to improve

- **What happened**: The published default integration command failed after
  merge although isolated integration passed.
  **Why**: Verification did not include a legacy default work directory created
  by an earlier coordinator version.
  **How to apply**: Execute the literal default command against supported legacy
  pre-state before marking a one-command gate passed.
  **Cites**: T1, T9, Phase 3 criteria 2–3
- **What happened**: Strict parity remained incompatible with all-nonconstant
  Neural Engine eligibility on the current compiler/hardware tuple.
  **Why**: Native FP16 SiLU introduced material divergence; F32/selective-F32
  variants either stayed outside bounds or introduced CPU-only operations.
  **How to apply**: Keep strict authority blocked and treat shadow output only as
  measurement evidence until a new compiler/graph contract passes both gates.
  **Cites**: T2, T8, Phase 3 criterion 4

### Process observations

- **What happened**: Matrix files initially existed without executing their
  claimed converter, compiler, and cancellation mechanisms.
  **Why**: Final-state assertions were mistaken for causal boundary evidence.
  **How to apply**: Retain exact pre-state, injection, exit, post-state,
  compensation, cancellation, and rerun for every durable transition.
  **Cites**: T4, T6, T9
- **What happened**: More than 21 review checkpoints were needed, while the
  progress frontmatter still reported zero rounds and comments.
  **Why**: The ledger narrative survived but aggregate counters were not updated
  at each verdict.
  **How to apply**: Increment structured counters with every review transition;
  use the narrative only as a recovery source.
  **Cites**: T3

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| Make the exact default integration command safely rerunnable with supported legacy work directories | edge-case | P1 | `ROADMAP.md` gate 7 |
| Obtain a strict parity-qualified, digest-bound receipt | performance | P1 | `ROADMAP.md` gate 2 |
| Retain observed Neural Engine placement evidence | performance | P1 | `ROADMAP.md` gate 3 |
| Measure latency, RSS, and energy only after qualification and placement | performance | P2 | `ROADMAP.md` gates 4–6 |

## Lessons

- An isolated override proves that a path can work; only the literal default
  command against legacy state proves that the operator workflow works.
- Mutation evidence must execute the named failure mechanism—correct final bytes
  alone do not prove which boundary failed.
- A successful capability preflight is not authority invalidation; the TOCTOU
  gap remains a separate state transition.

## Compounding

- compound invocation: `Documentation complete — docs/solutions/workflow-issues/verify-exact-default-commands-against-legacy-state.md`
