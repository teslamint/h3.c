# U4 qualification / rollback-compensation

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `qualification`
- Source commit: `396205de2d7f3483b68438d96df89d1157cf1dde`
- Fixture identity: `h3-u4-evidence-mearkrwn`
- Timestamp: `2026-08-11T15:58:21Z`
- Disposable fixture root: `/private/tmp/h3-u4-evidence-mearkrwn`
- Complete configured target inventory: `/private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc, /private/tmp/h3-u4-evidence-mearkrwn/qualification/result.json, /private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc.qualification.json, /private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc.qualification.json.invalid`
- Stub identity: `none`
- Boundary sentinel: `/private/tmp/h3-u4-evidence-mearkrwn/BOUNDARY_SENTINEL_NO_REAL_TARGETS` existed during the fixture run with the recorded no-real-targets marker; every configured target resolved below the disposable fixture root, so no real target or source weights was reachable.
- Pre-state: passing receipt exists
- Exact injection/command: `rename receipt to .disabled`
- Exit status: `0`
- Sanitized output: `receipt disabled`
- Post-state: fixed receipt path absent; runtime cannot authorize
- Next invocation / compensation result: passing qualification recreates fixed receipt
- Mechanism check: fixed-path removal disables non-shadow load without mutating model
