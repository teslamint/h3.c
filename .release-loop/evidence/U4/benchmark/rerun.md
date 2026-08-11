# U4 benchmark / rerun

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `benchmark`
- Source commit: `396205de2d7f3483b68438d96df89d1157cf1dde`
- Fixture identity: `h3-u4-evidence-mearkrwn`
- Timestamp: `2026-08-11T15:58:21Z`
- Disposable fixture root: `/private/tmp/h3-u4-evidence-mearkrwn`
- Complete configured target inventory: `/private/tmp/h3-u4-evidence-mearkrwn/benchmark/model.mlmodelc, /private/tmp/h3-u4-evidence-mearkrwn/benchmark/ab.json, /private/tmp/h3-u4-evidence-mearkrwn/benchmark/.ab.json.tmp-*`
- Stub identity: `deterministic timing seam`
- Boundary sentinel: `/private/tmp/h3-u4-evidence-mearkrwn/BOUNDARY_SENTINEL_NO_REAL_TARGETS` existed during the fixture run with the recorded no-real-targets marker; every configured target resolved below the disposable fixture root, so no real target or source weights was reachable.
- Pre-state: complete prior evidence exists
- Exact injection/command: `run same complete benchmark again`
- Exit status: `0`
- Sanitized output: `40 replacement samples`
- Post-state: one complete final JSON; no append/temp
- Next invocation / compensation result: analyzer accepts replacement
- Mechanism check: sample count remains 40 rather than 80, proving replacement
