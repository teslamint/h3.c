# U4 benchmark / cancellation-abort

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `benchmark`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/model.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/ab.json, /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/ab.json.tmp-*`
- Stub identity: `abort-after-sample seam`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: evidence absent
- Exact injection/command: `H3_ANE_TEST_ABORT_AFTER=3 H3_ANE_TEST_METAL_SECONDS=1.0 H3_ANE_TEST_COREML_SECONDS=0.8 /Users/teslamint/workspace/h3.c/h3_ane_bench_test --backend ab --coreml-model /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/model.mlmodelc --warmup 2 --pairs 20 --output /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/ab.json`
- Exit status: `130`
- Sanitized output: `pair 0 metal complete pair 0 coreml complete`
- Post-state: final and owned temp JSON absent
- Next invocation / compensation result: fresh command exits 0
- Mechanism check: compiled seam triggers cleanup before publish
