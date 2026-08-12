# ANE Shadow Receipt Preflight Addendum

Date: 2026-08-12
Approved by: user
Status: approved

## Original contract

`docs/deviations/2026-08-12-ane-shadow-measurement.md` requires every started
shadow measurement to invalidate existing strict qualification authority and
leave no authorizing receipt on success, failure, or cancellation.

## Discovered boundary

The qualifier stores strict authority beside the compiled model. If that
directory becomes non-writable, a process without additional privileges cannot
safely rename or unlink an existing receipt. Following or truncating the
receipt path is prohibited because it can damage symlink or hardlink targets.
Consequently, the original unconditional no-authority postcondition cannot be
achieved after shadow execution begins unless receipt invalidation capability is
proved first.

## Approved preflight contract

Before measuring or mutating any authority state, shadow mode must prove that
the receipt directory supports its link-safe same-directory quarantine
operation. The preflight uses a disposable sibling entry and must not modify the
compiled model, source weights, existing receipt, or result destination.

If preflight succeeds, the original shadow-only contract applies unchanged:
the live receipt pathname is invalidated before measurement and no shadow
outcome publishes replacement authority.

If preflight fails:

- shadow measurement does not start;
- the existing receipt and authority state remain unchanged;
- the process exits 2 with a stable structured receipt/preflight diagnostic;
- the result records `measurement_started: false` and
  `authority_state: "unchanged"` when its independently writable destination
  can be published;
- the coordinator reports the same non-started state and must not claim that
  authority was removed;
- no placement, parity, latency, memory, or energy evidence is accepted from
  that invocation.

This exception applies only to shadow measurement preflight. Strict
qualification, receipt validation, runtime adoption, and Metal fallback remain
unchanged.

## Additional diagnostic correction

The integration coordinator must accept every legitimate production
stage/code pair, including `compute_plan` inventory and allocation failures,
while rejecting inconsistent stage/code/context combinations. Its tests must
be checked against the production diagnostic table rather than only against a
self-authored coordinator mapping.

## Acceptance evidence

1. A writable receipt directory passes preflight without changing an existing
   receipt before quarantine begins.
2. A non-writable receipt directory exits 2 before measurement, preserves the
   receipt byte-for-byte, and emits the explicit non-started/unchanged state.
3. A pending signal during successful invalidation is handled only after the
   live receipt pathname becomes non-authorizing.
4. Production `compute_plan` allocation, empty, limit, nesting, and
   count/fill-change diagnostics pass coordinator validation with exact context.
5. Existing adversarial symlink/hardlink tests, strict qualification, and
   non-authorizing real shadow measurement remain green.

## Traceability

- Original spec: `docs/specs/2026-08-12-ane-eligibility-fix-design.md`
- Original plan: `docs/plans/2026-08-12-001-feat-ane-eligibility-fix-plan.md`
- Parent deviation: `docs/deviations/2026-08-12-ane-shadow-measurement.md`
- Affected unit: U4 compiler-to-receipt integration gate
- Review trigger: U4 shadow review round 3 surviving P1 findings
