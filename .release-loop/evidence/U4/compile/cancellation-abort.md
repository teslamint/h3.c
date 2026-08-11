# U4 compile / cancellation-abort

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `compile`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/compile/ane.mlpackage, /private/tmp/h3-u4-authoritative-uizkm1rc/compile/ane.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/compile/.ane.mlmodelc.compile-*, /private/tmp/h3-u4-authoritative-uizkm1rc/compile/bin/xcrun`
- Stub identity: `xcrun stub cancellation after partial output`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: destination absent
- Exact injection/command: `INJECT_CANCEL=1 PATH=/private/tmp/h3-u4-authoritative-uizkm1rc/compile/bin:$PATH /opt/homebrew/opt/python@3.14/bin/python3.14 /private/tmp/h3-u4-authoritative-uizkm1rc/compile/driver.py compile /private/tmp/h3-u4-authoritative-uizkm1rc/compile/ane.mlpackage /private/tmp/h3-u4-authoritative-uizkm1rc/compile/ane.mlmodelc`
- Exit status: `130`
- Sanitized output: `compiler exit 130`
- Post-state: destination and owned compile temp absent; receipt absent
- Next invocation / compensation result: clean command exits 0 after cancellation
- Mechanism check: stub exits 130 after partial temp model; production finally removes entire owned temp
