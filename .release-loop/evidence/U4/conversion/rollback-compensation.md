# U4 conversion / rollback-compensation

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `conversion`
- Source commit: `396205de2d7f3483b68438d96df89d1157cf1dde`
- Fixture identity: `h3-u4-evidence-mearkrwn`
- Timestamp: `2026-08-11T15:58:20Z`
- Disposable fixture root: `/private/tmp/h3-u4-evidence-mearkrwn`
- Complete configured target inventory: `/private/tmp/h3-u4-evidence-mearkrwn/conversion/ane-visual-block.mlpackage, /private/tmp/h3-u4-evidence-mearkrwn/conversion/.ane-visual-block.mlpackage.tmp-*`
- Stub identity: `none`
- Boundary sentinel: `/private/tmp/h3-u4-evidence-mearkrwn/BOUNDARY_SENTINEL_NO_REAL_TARGETS` existed during the fixture run with the recorded no-real-targets marker; every configured target resolved below the disposable fixture root, so no real target or source weights was reachable.
- Pre-state: complete unqualified package exists
- Exact injection/command: `shutil.rmtree(package)`
- Exit status: `0`
- Sanitized output: `unqualified package deleted`
- Post-state: package absent; source sentinel remains
- Next invocation / compensation result: conversion can reproduce package from immutable fixture
- Mechanism check: only destination was deleted; source boundary sentinel remains
