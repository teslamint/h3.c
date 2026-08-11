# U4 compile / success

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `compile`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/compile/ane.mlpackage, /private/tmp/h3-u4-authoritative-uizkm1rc/compile/ane.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/compile/.ane.mlmodelc.compile-*, /private/tmp/h3-u4-authoritative-uizkm1rc/compile/bin/xcrun`
- Stub identity: `xcrun stub validates exact argv and writes owned temp output`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: complete package; destination absent
- Exact injection/command: `PATH=/private/tmp/h3-u4-authoritative-uizkm1rc/compile/bin:$PATH /opt/homebrew/opt/python@3.14/bin/python3.14 /private/tmp/h3-u4-authoritative-uizkm1rc/compile/driver.py compile /private/tmp/h3-u4-authoritative-uizkm1rc/compile/ane.mlpackage /private/tmp/h3-u4-authoritative-uizkm1rc/compile/ane.mlmodelc`
- Exit status: `0`
- Sanitized output: `ok`
- Post-state: complete mlmodelc atomically published; compile temp absent
- Next invocation / compensation result: compiled marker readable; no receipt exists
- Mechanism check: production compile_package required exactly one mlmodelc before publish
