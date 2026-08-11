# U4 benchmark / rollback-compensation

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `benchmark`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/model.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/ab.json, /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/ab.json.tmp-*`
- Stub identity: `none`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: complete evidence exists
- Exact injection/command: `unlink /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/ab.json`
- Exit status: `0`
- Sanitized output: `deleted disposable benchmark evidence`
- Post-state: evidence absent; model fixture unchanged
- Next invocation / compensation result: fresh benchmark recreates evidence with exit 0
- Mechanism check: only output path removed
