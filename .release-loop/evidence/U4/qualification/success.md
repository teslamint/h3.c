# U4 qualification / success

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `qualification`
- Source commit: `396205de2d7f3483b68438d96df89d1157cf1dde`
- Fixture identity: `h3-u4-evidence-mearkrwn`
- Timestamp: `2026-08-11T15:58:21Z`
- Disposable fixture root: `/private/tmp/h3-u4-evidence-mearkrwn`
- Complete configured target inventory: `/private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc, /private/tmp/h3-u4-evidence-mearkrwn/qualification/result.json, /private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc.qualification.json, /private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc.qualification.json.invalid`
- Stub identity: `H3_ANE_TOOL_TESTING metrics seam; real directory digest`
- Boundary sentinel: `/private/tmp/h3-u4-evidence-mearkrwn/BOUNDARY_SENTINEL_NO_REAL_TARGETS` existed during the fixture run with the recorded no-real-targets marker; every configured target resolved below the disposable fixture root, so no real target or source weights was reachable.
- Pre-state: compiled model exists; receipt absent
- Exact injection/command: `H3_ANE_TEST_METRICS=0.001,0.01 /Users/teslamint/workspace/h3.c/h3_ane_qualification_test --model unused --coreml-model /private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc --output /private/tmp/h3-u4-evidence-mearkrwn/qualification/result.json`
- Exit status: `0`
- Sanitized output: `{"schema":"h3-ane-qualification/v1","status":"passed","model_sha256":"4460992ef1d2f53c03cf31e5396725c9e0a755a9cacebcf300a5374fb9ac939a","source_sha256":"1111111111111111111111111111111111111111111111111111111111111111","test_vector":"xorshift32-v1","qualified_at":"2026-08-11T15:58:21Z","max_abs":0.001,"relative_l2":0.01,"receipt_path":"/private/tmp/h3-u4-evidence-mearkrwn/qualification/model.mlmodelc.qualification.json","failure_reason":null}`
- Post-state: one passing receipt bound to current digests
- Next invocation / compensation result: receipt parser-compatible fields and result status passed
- Mechanism check: strict metrics are below both bounds and receipt exists only after result computation
