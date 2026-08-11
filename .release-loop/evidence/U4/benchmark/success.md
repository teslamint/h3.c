# U4 benchmark / success

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `benchmark`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/model.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/ab.json, /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/ab.json.tmp-*`
- Stub identity: `compiled deterministic timing/placement seam`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: qualified-shaped fixture; evidence absent
- Exact injection/command: `H3_ANE_TEST_METAL_SECONDS=1.0 H3_ANE_TEST_COREML_SECONDS=0.8 /Users/teslamint/workspace/h3.c/h3_ane_bench_test --backend ab --coreml-model /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/model.mlmodelc --warmup 2 --pairs 20 --output /private/tmp/h3-u4-authoritative-uizkm1rc/benchmark/ab.json`
- Exit status: `0`
- Sanitized output: `pair 0 metal complete pair 0 coreml complete pair 1 coreml complete pair 1 metal complete pair 2 metal complete pair 2 coreml complete pair 3 coreml complete pair 3 metal complete pair 4 metal complete pair 4 coreml complete pair 5 coreml complete pair 5 metal complete pair 6 metal complete pair 6 c`
- Post-state: 40 ordered samples atomically published with observed placement
- Next invocation / compensation result: production analyzer accepts claim fixture
- Mechanism check: exit 0, exact AB/BA order, and placement derives from stats seam
