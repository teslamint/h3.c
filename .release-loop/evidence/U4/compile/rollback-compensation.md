# U4 compile / rollback-compensation

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `compile`
- Source commit: `396205de2d7f3483b68438d96df89d1157cf1dde`
- Fixture identity: `h3-u4-evidence-mearkrwn`
- Timestamp: `2026-08-11T15:58:21Z`
- Disposable fixture root: `/private/tmp/h3-u4-evidence-mearkrwn`
- Complete configured target inventory: `/private/tmp/h3-u4-evidence-mearkrwn/compile/ane.mlpackage, /private/tmp/h3-u4-evidence-mearkrwn/compile/compiled, /private/tmp/h3-u4-evidence-mearkrwn/compile/bin/xcrun`
- Stub identity: `none`
- Boundary sentinel: `/private/tmp/h3-u4-evidence-mearkrwn/BOUNDARY_SENTINEL_NO_REAL_TARGETS` existed during the fixture run with the recorded no-real-targets marker; every configured target resolved below the disposable fixture root, so no real target or source weights was reachable.
- Pre-state: compiled directory exists; package retained
- Exact injection/command: `shutil.rmtree(compiled_output)`
- Exit status: `0`
- Sanitized output: `compiled output deleted`
- Post-state: package remains reproducible
- Next invocation / compensation result: compile succeeds again from package
- Mechanism check: only compiled output removed and source package stayed
