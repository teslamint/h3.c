# U4 qualification / success

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `qualification`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json.invalid, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json.tmp-*`
- Stub identity: `compiled H3_ANE_TOOL_TESTING metrics seam with real directory digest`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: compiled model; receipt absent
- Exact injection/command: `H3_ANE_TEST_METRICS=0.001,0.01 H3_ANE_TEST_SOURCE_SHA256=1111111111111111111111111111111111111111111111111111111111111111 /Users/teslamint/workspace/h3.c/h3_ane_qualification_test --model unused --coreml-model /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc --output /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json`
- Exit status: `0`
- Sanitized output: `(no output)`
- Post-state: RESULT exists and receipt was published last
- Next invocation / compensation result: runtime receipt parser accepts exact fields
- Mechanism check: both metrics strict-pass and final receipt exists after RESULT
