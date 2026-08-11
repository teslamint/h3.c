# U4 qualification / cancellation-abort

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `qualification`
- Source commit: `396205de2d7f3483b68438d96df89d1157cf1dde`
- Fixture identity: `h3-u4-evidence-mearkrwn`
- Timestamp: `2026-08-11T15:58:21Z`
- Disposable fixture root: `/private/tmp/h3-u4-evidence-mearkrwn`
- Complete configured target inventory: `/private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc, /private/tmp/h3-u4-evidence-mearkrwn/qualification/result.json, /private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc.qualification.json, /private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc.qualification.json.invalid`
- Stub identity: `signal boundary fixture after real invalidation transition`
- Boundary sentinel: `/private/tmp/h3-u4-evidence-mearkrwn/BOUNDARY_SENTINEL_NO_REAL_TARGETS` existed during the fixture run with the recorded no-real-targets marker; every configured target resolved below the disposable fixture root, so no real target or source weights was reachable.
- Pre-state: old receipt exists
- Exact injection/command: `qualification invalidation step; inject SIGINT before parity execution`
- Exit status: `130`
- Sanitized output: `signal exit 130`
- Post-state: prior receipt remains .invalid; live receipt and receipt temp absent
- Next invocation / compensation result: clean passing run is required to restore authority
- Mechanism check: fixed live path is absent and temp glob empty, so runtime cannot load stale authority
