# U4 qualification / cancellation-abort

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `qualification`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json.invalid, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json.tmp-*`
- Stub identity: `compiled pause-after-invalidation seam`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: old passing receipt exists
- Exact injection/command: `H3_ANE_TEST_PAUSE_AFTER_INVALIDATION=/private/tmp/h3-u4-authoritative-uizkm1rc/qualification/invalidated /Users/teslamint/workspace/h3.c/h3_ane_qualification_test --model unused --coreml-model /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc --output /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json; kill -TERM after marker`
- Exit status: `143`
- Sanitized output: `terminated after invalidation marker`
- Post-state: prior receipt remains .invalid; live receipt/result temp absent
- Next invocation / compensation result: clean strict-pass command restores authority with exit 0
- Mechanism check: marker is written only after production rename invalidates fixed receipt; SIGTERM cleanup leaves no authorizing path
