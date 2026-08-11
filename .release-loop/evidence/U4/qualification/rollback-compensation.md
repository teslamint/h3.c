# U4 qualification / rollback-compensation

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `qualification`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json.invalid, /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/result.json.tmp-*`
- Stub identity: `none`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: passing receipt exists
- Exact injection/command: `mv /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json /private/tmp/h3-u4-authoritative-uizkm1rc/qualification/model.mlmodelc.qualification.json.disabled`
- Exit status: `0`
- Sanitized output: `renamed live receipt to .disabled`
- Post-state: fixed live receipt path absent
- Next invocation / compensation result: passing qualification restores authority with exit 0
- Mechanism check: runtime fixed path is absent while model remains unchanged
