# U4 Shadow Measurement Report

Status: DONE

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

## TDD and verification

- Red tests first proved the qualifier rejected `--shadow-only`, the
  coordinator rejected `shadow`, and an out-of-bounds passing qualifier was
  initially accepted; the implementation then made each test pass.
- `python3 -m unittest tests/test_ane_tools.py`: 49 passed.
- `python3 -m py_compile scripts/run_ane_integration.py`: passed.
- `make h3_ane_tool_tests`: passed.
- Actual-Metal `./h3_ane_tests`: passed.
- Actual-Metal `make -j8 && make test`: passed; core suite reported 1,768
  checks and the installed Metal/audio suites passed (optional released-model
  fixtures remained skipped as reported by the suite).
- `git diff --check`: passed.

## Real FL2VA evidence

- `H3_ANE_WEIGHT_DIR=MiniMax-H3/FL2VA/video_vae/source make
  h3_ane_shadow_measurement_test`: exit 0.
- Retained evidence:
  `.release-loop/evidence/U4/shadow-measurement.json`.
- Result: passed, profile `shadow-measurement-v1`, authority false,
  `max_abs=0.19216197729110718`,
  `relative_l2=0.038400878187031535`, receipt null.
- Placement inventory remained 441 total / 149 nonconstant / 149
  Neural-Engine-supported / zero CPU-only / zero unknown nonconstant.
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
