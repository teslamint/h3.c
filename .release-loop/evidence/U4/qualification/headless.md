# U4 qualification / headless

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `qualification`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json.invalid, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json.tmp-*`
- Stub identity: `metrics seam`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: compiled model; stdin closed
- Exact injection/command: `H3_ANE_TEST_METRICS=0.001,0.01 H3_ANE_TEST_SOURCE_SHA256=1111111111111111111111111111111111111111111111111111111111111111 /Users/teslamint/workspace/h3.c/h3_ane_qualification_test --model unused --coreml-model /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc --output /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json < /dev/null`
- Exit status: `0`
- Sanitized output: `(no output)`
- Post-state: RESULT and final receipt written
- Next invocation / compensation result: same flags rerun with exit 0
- Mechanism check: no prompt and exact structured outputs
