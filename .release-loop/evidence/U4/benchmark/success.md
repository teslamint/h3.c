# U4 benchmark / success

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `benchmark`
- Source commit: `396205de2d7f3483b68438d96df89d1157cf1dde`
- Fixture identity: `h3-u4-evidence-mearkrwn`
- Timestamp: `2026-08-11T15:58:21Z`
- Disposable fixture root: `/private/tmp/h3-u4-evidence-mearkrwn`
- Complete configured target inventory: `/private/tmp/h3-u4-evidence-mearkrwn/benchmark/model.mlmodelc, /private/tmp/h3-u4-evidence-mearkrwn/benchmark/ab.json, /private/tmp/h3-u4-evidence-mearkrwn/benchmark/.ab.json.tmp-*`
- Stub identity: `native H3_ANE_TOOL_TESTING deterministic timing seam`
- Boundary sentinel: `/private/tmp/h3-u4-evidence-mearkrwn/BOUNDARY_SENTINEL_NO_REAL_TARGETS` existed during the fixture run with the recorded no-real-targets marker; every configured target resolved below the disposable fixture root, so no real target or source weights was reachable.
- Pre-state: qualified-shaped model fixture; evidence absent
- Exact injection/command: `/Users/teslamint/workspace/h3.c/h3_ane_bench_test --backend ab --coreml-model /private/tmp/h3-u4-evidence-mearkrwn/benchmark/model.mlmodelc --warmup 2 --pairs 20 --output /private/tmp/h3-u4-evidence-mearkrwn/benchmark/ab.json`
- Exit status: `0`
- Sanitized output: `40 ordered samples`
- Post-state: complete atomic JSON with 20 pairs
- Next invocation / compensation result: analyzer claim passes
- Mechanism check: 40 samples and alternating orders validate through production analyzer
