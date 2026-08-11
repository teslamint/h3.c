# Retro: ANE acceleration

- Date: 2026-08-12
- Source: local merge `553a09e` plus verified post-merge fixes through `bb4faa4`
- Spec: `docs/specs/2026-08-11-ane-acceleration-design.md`
- Plan: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md`

## Release data

| Metric | Value |
|---|---|
| **Changed non-test lines** | 3,494 (3,487 added + 7 removed) |
| Commits | 24 through final verified product commit `bb4faa4` |
| Review rounds | 7 fix/re-review rounds |
| Comments (fixed / deferred) | 30 / 0 |
| CI failures | 0; no writable remote/CI was available, so local actual-Metal verification was authoritative |
| Duration (first spec commit → merge) | 9 hours 18 minutes |
| Units planned / completed | 5 / 5 |

## Success criteria: measured vs declared

| # | Declared criterion | Measurement (command / rubric) | Measured result | Verdict |
|---|---|---|---|---|
| 1 | Default build and runtime remain Metal-only. | `make clean && make -j8 && make test && make h3_ane_tests && ./h3_ane_tests` | verified: exact command exited 0 on actual Metal; `h3_tests` reported 1,768 checks and focused ANE tests passed with zero default load attempts | Met |
| 2 | Every configured Core ML failure returns to unchanged Metal without contamination. | `make h3_ane_tests && ./h3_ane_tests` | verified: focused suite passed genuine receipt/fingerprint/load/plan-unavailable dispatch, pointer-identical Metal adoption, shadow, allocation, and cancellation regressions | Met |
| 3 | Fixed FL2VA artifact passes parity before non-shadow execution. | `make h3_ane_qualification && ./h3_ane_qualification --model MiniMax-H3/FL2VA/video_vae/source --coreml-model "$H3_ANE_MODEL" --output .release-loop/evidence/ane-qualification.json` | verified: command exited 1; RESULT was `failed` with matching digests and `ANE backend is unavailable`; no qualification receipt exists | Not met — real qualification did not pass and the exact failure stage remains unknown |
| 4 | ANE use is never inferred from configuration or compute-plan eligibility. | Reviewer rubric over code, docs, and retained evidence | verified: final branch re-review confirmed eligibility/preference labels are not observed placement and no acceleration claim exists | Met |
| 5 | At least 20 alternating A/B pairs support the latency calculation. | `./scripts/analyze_ane_benchmark.py .release-loop/evidence/ane-ab.json` | verified: executable command exited 2 because no qualified A/B artifact exists | Not met — benchmarking is correctly blocked by failed qualification |
| 6 | Process memory includes Core ML allocations and stays within the declared bound. | Exact paired `/usr/bin/time -l` commands | verified: Metal command exited 0 with 20 samples and maximum RSS 875,560,960 bytes; Core ML command exited 1 at `ANE backend is unavailable` and wrote no JSON | Partially met — Metal baseline exists, but no valid Core ML comparison exists |
| 7 | Energy is measured independently on the same A/B workload. | Instruments Energy/Neural Engine trace rubric | unverified: no qualified Core ML workload or retained real energy/Neural Engine trace exists | Not met — placement and energy remain unmeasured |
| 8 | The experiment remains isolated and removable. | Final reviewer rubric | verified: final re-review found no public `h3.h` change, no per-operator ANE dispatch, and isolated private bridge/selection files | Met |

Outcome: delivered and locally merged a default-off, fingerprint- and
receipt-gated ANE measurement harness with Metal fail-closed behavior (criteria
1, 2, 4, and 8 met). ANE acceleration was not demonstrated: real qualification
failed and no receipt exists, so criteria 3, 5, and 7 are not met and criterion
6 is only partial. Plan completion records safe harness delivery, not ANE
qualification, placement, energy, memory, or speed.

## Carry-forward from previous retro

| Item | Status | Evidence |
|---|---|---|
| No previous retro items | Done | This is the repository's first retro document. |

- Previous doc shape: no previous retro doc

## Interview Transcript

- Independence level: same-model fresh-context
- Rounds used: 5 (max 5)

| ID | Round | Phase | Probe | Answer | Evidence | Verdict (verbatim) |
|---|---:|---:|---|---|---|---|
| T1 | 1→2 | 5 | Which choices prove pointer-identical fail-closed Metal behavior? | U3 uses genuine unavailable handles, exact input pointer assertions, stable accounting, and synchronized cancellation. | `396205d`, U3 evidence, focused tests | accepted |
| T2 | 1→2 | 5 | What does the failed real qualification prove and leave unknown? | It proves fail-closed digests/no receipt, but the generic reason does not locate the stage; criteria 3 and 5–7 remain blocked. | Phase 3 criterion 3; U4 result | accepted |
| T3 | 1→2 | 5 | Which late findings caused the most rework? | U4 metadata, atomicity, evidence provenance, and graph-execution gaps dominated; a package-to-runtime gate would have caught them. | U4 review rounds; `a113bc7` | accepted |
| T4 | 1→2 | 5 | Why did two operator fixes land after merge? | Pre-merge checks used substitute invocations and synthetic dtypes instead of exact commands with real weights. | `0252b1e`, `bb4faa4`, Phase 3 | accepted |
| T5 | 1→2 | 4 | What is the ordered carry-forward gate? | Stage diagnostics, qualification, observed placement, latency, RSS, and energy; every failure blocks later work. | `ROADMAP.md` | accepted |
| T6 | 2→3 | 5 | What diagnostic change locates qualification failure? | Add structured stage/reason/operation/device fields and table-driven failure fixtures; retain RESULT plus trace summary. | `ROADMAP.md` gate 1 | accepted |
| T7 | 2→3 | 5 | What one-command U4 gate is needed? | Exercise tiny package generation, compile, runtime metadata, graph/reference parity, and receipt publication in one pinned chain. | `ROADMAP.md` gate 7 | accepted |
| T8 | 2→3 | 5 | What lifecycle state accounts for post-merge fixes? | Merge `553a09e` is not terminal product evidence; final verified product commit is `bb4faa4`. | git log; Phase 3 exact commands | accepted |
| T9 | 2→3 | 4 | How does a local roadmap remain actionable? | Ordered statuses, one human owner, sanitized evidence paths, and hard prerequisite blocking. | `ROADMAP.md` | accepted |
| T10 | 2→3 | 5 | Which U3 checks permanently block releases? | Genuine failure handles, pointer identity, Metal adoption, accounting, shadow, allocation, and cancellation in `h3_ane_tests`. | criterion 2 measurement | accepted |
| T11 | 3→4 | 5 | Where is final verified state recorded without breaking the plan seal? | Mutable plan frontmatter records `status: done` and `completed_by: bb4faa4`; git evidence resolves conflicts. | plan/v1 schema and this commit | accepted |
| T12 | 3→4 | 4 | What evidence is safe to commit? | Bounded sanitized summaries only; raw traces, models, media, private paths, identifiers, and large logs stay local. | `ROADMAP.md` evidence policy | accepted |
| T13 | 3→4 | 4 | Which carry-forwards block retro closure? | Roadmap, lifecycle correction, exact measurements, and permanent U3 test verification close now; stage diagnostics/integration gate remain tracked. | Phase 3; `ROADMAP.md` | accepted |
| T14 | 3→4 | 3 | What exact criterion checklist applies at `bb4faa4`? | Criteria 1/2/4/8 pass; 3/5/7 fail closed; 6 has only the Metal half. | Success criteria table | accepted |
| T15 | 4→5 | 5 | How is release blocking enforced without CI? | Root verifier runs the exact suite on merged main with actual Metal; restricted-sandbox probe failures cannot approve release. | progress ship log; criterion 1 | accepted |
| T16 | 4→5 | 4 | What priority/trigger applies to stage diagnostics? | P1 when qualification fails generically; graph redesign and all downstream benchmarking remain blocked. | `ROADMAP.md` gate 1 | accepted |
| T17 | 4→5 | 5 | How should the outcome avoid overstating acceleration? | State safe harness delivery separately from unmet qualification, placement, latency, memory, and energy evidence. | Outcome paragraph; Phase 3 | accepted |

Facilitator terminal verdict: “No further probes; the retrospective has
converged on evidence-backed outcomes, closure requirements, and carry-forward
priorities.”

## Findings

### What worked well

- **What happened**: Genuine boundary failures and pointer-identity tests made
  the optional backend fail closed rather than merely report success in mocks.
  **Why**: U3 routed real unavailable handles through one dispatcher and reviewed
  all six transition outcomes.
  **How to apply**: Keep `h3_ane_tests` as a release blocker on actual Metal.
  **Cites**: T1, T10, Phase 3 criterion 2
- **What happened**: Reviews stopped compute-plan preference from becoming an
  observed-placement claim.
  **Why**: The evidence ladder was applied again at full-branch scope.
  **How to apply**: Label eligibility, qualification, placement, and performance
  separately in every accelerator backend.
  **Cites**: T2, Phase 3 criterion 4

### What to improve

- **What happened**: Real qualification failed with a generic backend-unavailable
  result, leaving the failure stage unknown.
  **Why**: Qualification retained a safe terminal result but not structured
  contract/receipt/compute-plan/load/placement/prediction stage evidence.
  **How to apply**: Implement the P1 stage-diagnostic gate before redesign or
  benchmarking.
  **Cites**: T2, T6, T16, Phase 3 criterion 3
- **What happened**: Script permissions and real benchmark dtype were discovered
  only after merge.
  **Why**: Pre-merge verification substituted `python3`/synthetic fixtures for
  the exact published operator commands and real checkpoint format.
  **How to apply**: Execute every declared criterion command verbatim before the
  merge gate, including production-format artifacts.
  **Cites**: T4, T14, Phase 3 criteria 5–6

### Process observations

- **What happened**: U4 required the largest review correction because unit
  tests did not initially cross package, compiler, runtime, and receipt
  boundaries.
  **Why**: Each layer looked locally correct while metadata and atomicity drifted
  between them.
  **How to apply**: Require one pinned package-to-receipt integration command
  before accepting conversion tooling.
  **Cites**: T3, T7
- **What happened**: Local merge could be responsibly verified without GitHub
  CI only because actual-Metal post-merge commands were mandatory and recorded.
  **Why**: The process distinguished sandbox/tooling failures from product
  failures and refused lower-tier evidence.
  **How to apply**: Keep merge approval blocked until merged-main tests run on
  the real device whenever remote CI is unavailable.
  **Cites**: T8, T15

## Carry-forward items registered

| Item | Type | Priority | Tracked at |
|---|---|---|---|
| Add stage-specific qualification failure diagnostics | edge-case | P1 | `ROADMAP.md` gate 1 |
| Obtain a passing fixed-block qualification receipt | performance | P1 | `ROADMAP.md` gate 2 |
| Retain observed Neural Engine placement evidence | performance | P1 | `ROADMAP.md` gate 3 |
| Measure latency, RSS, and energy in order | performance | P2 | `ROADMAP.md` gates 4–6 |
| Add a one-command package-to-receipt integration gate | process | P2 | `ROADMAP.md` gate 7 |

## Lessons

- Compute-plan eligibility is not observed accelerator execution; only a
  retained runtime trace can cross that evidence boundary.
- A documented command is part of the product: substitutes and help output do
  not prove that exact executable, artifact dtype, or workflow.
- Safe harness completion and acceleration success are separate outcomes; a
  failed qualification can validate the former while disproving the latter.

## Compounding

- compound invocation: `Documentation complete — docs/solutions/best-practices/distinguish-ane-eligibility-from-observed-execution.md`
