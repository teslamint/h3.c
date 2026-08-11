# U4 benchmark / forced-failure

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `benchmark`
- Source commit: `396205de2d7f3483b68438d96df89d1157cf1dde`
- Fixture identity: `h3-u4-evidence-mearkrwn`
- Timestamp: `2026-08-11T15:58:21Z`
- Disposable fixture root: `/private/tmp/h3-u4-evidence-mearkrwn`
- Complete configured target inventory: `/private/tmp/h3-u4-evidence-mearkrwn/benchmark/model.mlmodelc, /private/tmp/h3-u4-evidence-mearkrwn/benchmark/ab.json, /private/tmp/h3-u4-evidence-mearkrwn/benchmark/.ab.json.tmp-*`
- Stub identity: `native abort-after-sample seam`
- Boundary sentinel: `/private/tmp/h3-u4-evidence-mearkrwn/BOUNDARY_SENTINEL_NO_REAL_TARGETS` existed during the fixture run with the recorded no-real-targets marker; every configured target resolved below the disposable fixture root, so no real target or source weights was reachable.
- Pre-state: evidence absent
- Exact injection/command: `H3_ANE_TEST_ABORT_AFTER=3 /Users/teslamint/workspace/h3.c/h3_ane_bench_test --backend ab --coreml-model /private/tmp/h3-u4-evidence-mearkrwn/benchmark/model.mlmodelc --warmup 2 --pairs 20 --output /private/tmp/h3-u4-evidence-mearkrwn/benchmark/ab.json`
- Exit status: `130`
- Sanitized output: `injected odd-sample interruption`
- Post-state: final JSON absent; temp removed
- Next invocation / compensation result: fresh complete run succeeds
- Mechanism check: exit 130 occurs after sample 3 and no final rename occurs
