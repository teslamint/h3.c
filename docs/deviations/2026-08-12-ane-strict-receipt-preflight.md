# ANE Strict Receipt Preflight Addendum

Date: 2026-08-12
Approved by: user
Status: approved

## Original contract

The approved design and plan require every failed strict qualification to leave
no authorizing receipt. They also require a writable result destination to
receive the first stable structured failure.

## Discovered boundary

A strict receipt is stored beside the compiled model. When that directory is
not writable, a process cannot safely rename or unlink an existing receipt.
Following or truncating the receipt path is prohibited because it can damage a
symlink or hardlink target. Therefore the unconditional receipt-removal
postcondition cannot be satisfied after strict qualification starts unless
revocation capability is proved first.

## Approved preflight contract

Before strict qualification performs prediction, conversion that replaces an
existing qualified model, or any authority mutation, it must prove that the
receipt directory supports the same link-safe, same-directory quarantine used
for receipt invalidation. The preflight uses disposable sibling entries and
must not modify the compiled model, source weights, existing receipt, result
destination, or any link target.

If preflight succeeds, the original strict contract applies unchanged: any
existing receipt is invalidated before measurement, and every later failure
leaves no authorizing receipt.

If preflight fails:

- strict qualification does not start;
- an existing receipt and authority state remain byte-for-byte unchanged;
- the process exits 2 with stable `receipt/receipt_invalid` diagnostics;
- an independently writable result records `measurement_started: false`,
  `authority_state: "unchanged"`, `authority: false`, and
  `receipt_path: null`;
- if the result cannot be published, the same stable failure is written to
  stderr; and
- no parity, placement, latency, memory, energy, or production-authority claim
  is accepted from that invocation.

The coordinator must apply this check before destructively preparing or
replacing a reused strict work directory. It may reject reuse without mutation
when existing authority cannot be safely invalidated. An absent receipt is a
valid unchanged state; it must not be fabricated or treated as a snapshot
mismatch.

This exception does not authorize non-shadow Core ML output, weaken strict
parity bounds, or allow a stale receipt to authorize a new model. Runtime receipt
validation, Metal fallback, and the shadow-specific preflight contract remain
unchanged.

## Acceptance evidence

1. A writable receipt directory passes preflight without changing an existing
   receipt before invalidation begins.
2. A non-writable receipt directory exits 2 before qualification, preserves the
   receipt byte-for-byte, and publishes the explicit non-started/unchanged
   result when its destination is writable.
3. Coordinator reuse of a work directory containing strict authority never
   removes that authority before preflight; failure preserves it unchanged.
4. Successful preflight followed by any strict failure leaves no receipt.
5. Result-publication failure uses bounded stable stderr and cannot authorize
   runtime output.

## Traceability

- Original spec: `docs/specs/2026-08-12-ane-eligibility-fix-design.md`
- Original plan: `docs/plans/2026-08-12-001-feat-ane-eligibility-fix-plan.md`
- Parent receipt-preflight deviation:
  `docs/deviations/2026-08-12-ane-shadow-receipt-preflight.md`
- Affected units: U1 qualification diagnostics and U4 integration coordinator
- Review trigger: final branch review strict receipt invalidation failure
