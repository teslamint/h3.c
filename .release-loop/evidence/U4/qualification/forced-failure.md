# U4 qualification / forced-failure

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `qualification`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json.invalid, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json.tmp-*`
- Stub identity: `metrics seam threshold injection`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: old passing receipt exists
- Exact injection/command: `H3_ANE_TEST_METRICS=0.002,0.01 H3_ANE_TEST_SOURCE_SHA256=1111111111111111111111111111111111111111111111111111111111111111 /Users/teslamint/workspace/h3.c/h3_ane_qualification_test --model unused --coreml-model /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc --output /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json`
- Exit status: `1`
- Sanitized output: `(no output)`
- Post-state: old receipt is .invalid; live receipt absent; failed RESULT exists
- Next invocation / compensation result: new strict pass required
- Mechanism check: max_abs equality is exact failure boundary after invalidation
