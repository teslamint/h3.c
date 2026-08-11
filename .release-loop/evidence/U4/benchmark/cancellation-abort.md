# U4 benchmark / cancellation-abort

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `benchmark`
- Source commit: `396205de2d7f3483b68438d96df89d1157cf1dde`
- Fixture identity: `h3-u4-evidence-mearkrwn`
- Timestamp: `2026-08-11T15:58:21Z`
- Disposable fixture root: `/private/tmp/h3-u4-evidence-mearkrwn`
- Complete configured target inventory: `/private/tmp/h3-u4-evidence-mearkrwn/benchmark/model.mlmodelc, /private/tmp/h3-u4-evidence-mearkrwn/benchmark/ab.json, /private/tmp/h3-u4-evidence-mearkrwn/benchmark/.ab.json.tmp-*`
- Stub identity: `abort-after-sample seam models SIGINT cleanup`
- Boundary sentinel: `/private/tmp/h3-u4-evidence-mearkrwn/BOUNDARY_SENTINEL_NO_REAL_TARGETS` existed during the fixture run with the recorded no-real-targets marker; every configured target resolved below the disposable fixture root, so no real target or source weights was reachable.
- Pre-state: evidence absent
- Exact injection/command: `H3_ANE_TEST_ABORT_AFTER=3 benchmark CLI`
- Exit status: `130`
- Sanitized output: `exit 130`
- Post-state: final and temp evidence absent
- Next invocation / compensation result: fresh complete invocation succeeds
- Mechanism check: native cleanup removes temp and never renames partial JSON
