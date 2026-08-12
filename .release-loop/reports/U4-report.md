# U4 Shadow Measurement Report

Status: DONE

Final-review source commit: `4aa234fb6cd54d3b1ca198ed4da0177e5cb42c45`

## Authority boundary

- Added the explicit `--shadow-only` qualifier profile without changing the
  default strict `0.002 / 0.02` thresholds or strict receipt publication path.
- Shadow results use `profile: "shadow-measurement-v1"`, exact finite bounds
  `max_abs < 0.25` and `relative_l2 < 0.05`, and `authority: false`.
- Shadow mode invalidates a stale sidecar before measurement and never creates
  or preserves a qualification receipt on success, bounds failure, nonfinite
  metrics, result publication failure, or cancellation.
- The coordinator independently validates the shadow profile, bounds,
  threshold outcome, finite metrics, digests, and absence of a receipt before
  atomically publishing a passed non-authorizing summary.
- Receipt invalidation atomically renames only the receipt pathname to a unique
  sibling quarantine, without a pathname-unlink fallback. It never opens, truncates, or follows a receipt target. Symlink and hardlink adversarial tests
  prove an external sentinel remains byte-for-byte unchanged.
- SIGINT and SIGTERM are blocked across the entire invalidation critical
  section. A synchronized pending-signal test proves SIGTERM is handled only
  after the live receipt pathname becomes non-authorizing.
- Shadow now performs a side-effect-free disposable-sibling capability
  preflight before invalidation. A synchronized writable test proves the
  genuine receipt, model, weights, and result remain unchanged before
  quarantine. A non-writable-parent test exits 2 without measurement,
  preserves receipt bytes, and publishes `measurement_started: false` with
  `authority_state: "unchanged"` to a separate writable result path.
- Shadow failures retain the same complete structured diagnostic fields as the
  strict qualifier, and the coordinator validates and propagates
  `parity_bounds_failed` versus `parity_metrics_nonfinite` without collapsing
  them into a generic qualification failure.
- Coordinator inventory is a closed eight-field canonical object, serialized
  summaries are capped at 16,384 bytes, and output/work artifact aliases are
  rejected before work-directory mutation.
- Real/shadow output, work, and resolved source-weight trees must be pairwise
  disjoint before any coordinator mutation. Closed production stage/code
  taxonomy and stage-specific operation/device validation preserve every
  legitimate qualifier failure while rejecting fabricated context.
- Coordinator preflight failures preserve the explicit unchanged authority
  state and do not delete or claim removal of the genuine-format sidecar.
  Production-derived tests cover exact `compute_plan` pairs for allocation,
  empty inventory, limit, nesting, and count/fill change, including nullable
  or numeric observed-count/limit context.
- `authority_state: "unchanged"` is now grounded in nofollow regular-file
  snapshots taken after conversion and immediately after the qualifier child.
  Device, inode, mode, size, modification time, and SHA-256 must all match.
  A pre-seeded genuine receipt is accepted unchanged; a child that creates or
  changes authority while claiming unchanged is rejected and cleaned up.
- A synchronized writability TOCTOU test changes the receipt directory after a
  successful preflight. The native qualifier exits 2 before measurement,
  preserves the receipt byte-for-byte, and emits the same explicit structured
  non-started/unchanged result.
- The diagnostic contract is cross-checked against production record sites:
  fabricated eligibility/inventory pairs are removed, replacement-output
  allocation maps to `output/output_copy_failed`, eligibility requires operation context, and compute-plan inventory
  failures require the count context that production records.
- Final record-site correction places creator source SHA mismatch under
  `contract/fingerprint_mismatch`, receipt digest mismatch under
  `receipt/receipt_digest_mismatch`, and removes
  fabricated eligibility/inventory pairs. Compute-plan inventory empty/limit
  accept optional count context because `create_impl` emits them without it,
  while nesting and count/fill change require their production count context;
  compute-plan allocation accepts optional count context.
- Every coordinator shadow success, qualifier failure, summary-publication
  failure, and cancellation fixture independently seeds a genuine-format
  strict sidecar and proves the live authority pathname is absent afterward.

## TDD and verification

- Red tests first proved the qualifier rejected `--shadow-only`, the
  coordinator rejected `shadow`, and an out-of-bounds passing qualifier was
  initially accepted; the implementation then made each test pass.
- `python3 -m unittest discover -s tests -p 'test_ane_tools.py'`: 69 passed.
- `python3 -m py_compile scripts/run_ane_integration.py`: passed.
- `make h3_ane_tool_tests`: passed.
- Strict warning build (`-Wall -Wextra -Wpedantic -Wshadow -Wconversion`) and
  `clang --analyze` for `tests/qualify_ane.c`: passed with no findings. The
  reviewed short-circuit stream leak was fixed by always attempting
  `fflush`, `fsync`, and `fclose`.
- Actual-Metal `./h3_ane_tests`: passed.
- Actual-Metal `make -j8 && make test`: passed; core suite reported 1,768
  checks and the installed Metal/audio suites passed (optional released-model
  fixtures remained skipped as reported by the suite).
- `git diff --check`: passed.

## Real FL2VA evidence

- `H3_ANE_WEIGHT_DIR=MiniMax-H3/FL2VA/video_vae/source make
  h3_ane_shadow_measurement_test`: exit 0.
- Retained evidence:
  `.release-loop/evidence/U4/shadow-measurement.json` and the six-row reviewed
  manifest `.release-loop/evidence/U4/shadow-matrix-manifest.json`.
- Result: passed, profile `shadow-measurement-v1`, authority false,
  `max_abs=0.19216197729110718`,
  `relative_l2=0.038400878187031535`, receipt null.
- Compute-plan eligibility inventory remained 441 total / 149 nonconstant /
  149 Neural-Engine-supported / zero CPU-only / zero unknown nonconstant.
  This is eligibility evidence only; runtime Neural Engine placement was not
  observed and remains unclaimed.
- The compiled-model sidecar was absent after measurement.

## Strict fail-closed proof

- The unchanged strict real Make target was rerun with the same current FL2VA
  weights and disposable output/work paths.
- Make exited 2 after the coordinator's qualification child exited 1.
- The strict summary was `status: failed`, diagnostic
  `parity/parity_bounds_failed`, with the same measured metrics and
  `receipt: null`; the compiled-model qualification sidecar was absent.
- No shadow result can authorize runtime adoption; strict qualification and
  receipt validation remain the exclusive authority path.

## Final review evidence

- Exact source commit: `4aa234fb6cd54d3b1ca198ed4da0177e5cb42c45`.
- Fresh isolated synthetic integration passed `441/292/149/149/0` with null parity and receipt; `.release-loop/evidence/ane-integration.json` is the bounded summary.
- Fresh real shadow passed non-authorizing parity with no receipt; fresh strict real exited 1 at `parity/parity_bounds_failed` with no receipt.
- Actual disposable production-table evidence is retained in `.release-loop/evidence/U4/conversion.json`, `compile.json`, and `integration.json`.
- Strict and shadow qualification now preflight link-safe receipt invalidation before prediction or mutation; coordinator reuse applies the same preflight before deleting an owned work tree and accepts unchanged regular or absent authority snapshots.
