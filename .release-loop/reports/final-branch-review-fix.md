# Final branch review fix

## Findings resolved

- Benchmark `placement_summary` now identifies Metal as a backend and Core ML
  values as compute-plan preferences; it never labels a device mask as observed
  execution.
- A configured model fallback emits one stable concise diagnostic when either
  `H3_ANE_TRACE=1` or `H3_PROFILE=1`; the default-off path remains silent.
- `h3_ane_bench --coreml-model` uses the private explicit-authority constructor,
  so the CLI argument is sufficient while receipt, contract, fingerprint, and
  compute-plan validation remain unchanged.
- Core ML input/output transfer honors `MLMultiArray.strides`; canonical arrays
  retain the memcpy fast path and a padded noncontiguous fixture proves the
  stride-aware path in both directions.

## Verification

- `python3 -m unittest tests/test_ane_tools.py`: 16 tests passed.
- `./h3_ane_tests` with actual Metal access: passed.
- `git diff --check`: passed.
- The restricted sandbox run reached the expected Metal initialization failure;
  the same focused binary passed with actual Metal access.

## Remaining verification

- The final release-loop verifier still owns the production build and full
  actual-Metal `make test` rerun before advancing the phase.
