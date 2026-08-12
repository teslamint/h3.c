# ANE Shadow-Only Measurement Deviation

Date: 2026-08-12
Approved by: user
Status: approved

## Original contract

- `docs/specs/2026-08-12-ane-eligibility-fix-design.md` success criterion 4
  requires the real fixed FL2VA candidate to satisfy `max_abs < 0.002` and
  `relative_l2 < 0.02` before publishing an authorizing qualification receipt.
- `docs/plans/2026-08-12-001-feat-ane-eligibility-fix-plan.md` scenario S4 and
  U4 require the explicit real qualification target to pass those bounds and
  publish one digest-bound receipt.
- The plan's mutation matrix permits non-shadow Core ML output adoption only
  when a valid matching receipt exists.

## Evidence requiring deviation

The exact five-dimensional FP16 candidate passes the production inventory gate
with 441 total operations, 149 nonconstant operations, 149 Neural
Engine-supported operations, and zero CPU-only or unknown nonconstant
operations. On the target machine it fails strict Metal parity with
`max_abs = 0.19216197729110718` and
`relative_l2 = 0.038400878187031535`.

Bounded stage and isolated-operation probes identify native FP16 SiLU execution
under `CPUAndNeuralEngine` as the first material divergence. Full F32 restores
parity but makes the graph CPU-only. Selective F32 SiLU lowers the observed
error to `max_abs = 0.0042743682861328125` and
`relative_l2 = 0.0004873567215196463`, but introduces six CPU-only operations
and still misses the original maximum-absolute bound. No plan-conformant variant
was found that satisfies strict parity and all-nonconstant Neural Engine
eligibility on the current compiler, OS, and hardware tuple.

## Approved deviation

Add a distinct **shadow-only measurement** profile with provisional bounds:

- `max_abs < 0.25`
- `relative_l2 < 0.05`
- both metrics must be finite

Passing this profile means only that the current artifact is eligible for local
placement, latency, memory, and energy measurement while Core ML output is
discarded. It does not qualify numerical equivalence for production use.

The strict qualification profile and its `0.002 / 0.02` bounds remain
unchanged. Only that strict profile may publish an authorizing
`<MODEL.mlmodelc>.qualification.json` receipt or permit non-shadow Core ML
output adoption.

## Observable state contract

- Shadow measurement has an explicit CLI/Make entry point and emits a bounded,
  atomic result that identifies the profile, metrics, threshold outcome, and
  `authority: false`.
- A passing shadow measurement exits zero but never creates, preserves, or
  restores an authorizing receipt. Any pre-existing receipt is invalidated
  before measurement.
- A failed, cancelled, or unpublished shadow measurement also leaves no valid
  receipt and no temporary result.
- The integration summary records shadow measurement success separately from
  strict qualification. Its `receipt` field remains `null`.
- Runtime default-off behavior, Metal fallback, strict receipt validation, and
  request-output adoption rules do not change.
- Roadmap qualification gate 2 remains blocked. Shadow measurement may gather
  exploratory evidence for later gates but cannot mark qualification,
  placement, latency, memory, or energy gates passed by itself.

## Acceptance evidence

1. Boundary tests prove values just inside and outside `0.25 / 0.05`, nonfinite
   metrics, strict-profile preservation, and stable result fields.
2. Tests begin with a valid receipt and prove every shadow outcome removes or
   invalidates it and publishes no replacement.
3. Cancellation before result rename leaves no temporary result or receipt.
4. The real target-machine shadow run records the observed FP16 metrics,
   `authority: false`, `receipt: null`, and exit zero.
5. Existing strict real qualification continues to fail closed and publish no
   receipt for the same artifact.

## Traceability

- Original spec: `docs/specs/2026-08-12-ane-eligibility-fix-design.md`
- Original plan: `docs/plans/2026-08-12-001-feat-ane-eligibility-fix-plan.md`
- Affected scenario: S4 numerical qualification and authority
- Affected unit: U4 compiler-to-receipt integration gate
- Affected mutation rows: invalidate prior receipt, publish initial
  qualification RESULT, publish passing receipt, rewrite RESULT after receipt
  publication failure, and adopt Core ML request output

This addendum narrows the current release outcome to a safe measurement PoC. It
does not claim production qualification or observed Neural Engine placement.
