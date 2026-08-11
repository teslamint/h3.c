# U4 conversion / headless

- Plan identity: `docs/plans/2026-08-11-001-feat-ane-acceleration-plan.md` (`plan/v1`, U4)
- Matrix row: `conversion`
- Source commit: `a113bc70ff9ea9774cbe4eeae7a5d5cf50d5e5fd`
- Fixture identity: `h3-u4-authoritative-uizkm1rc`
- Timestamp: `2026-08-11T16:24:32Z`
- Disposable fixture root: `/private/tmp/h3-u4-authoritative-uizkm1rc`
- Complete configured target inventory: `/private/tmp/h3-u4-authoritative-uizkm1rc/conversion/driver.py, /private/tmp/h3-u4-authoritative-uizkm1rc/conversion/ane.mlpackage, /private/tmp/h3-u4-authoritative-uizkm1rc/conversion/.ane.mlpackage.tmp-*`
- Stub identity: `FakeModel local package writer`
- Boundary sentinel: `/private/tmp/h3-u4-authoritative-uizkm1rc/BOUNDARY_SENTINEL_NO_REAL_TARGETS` contained `all configured targets are disposable children of this root`; all command paths below resolve within that inventory, and no real weights were configured.
- Pre-state: destination absent; stdin closed
- Exact injection/command: `/opt/homebrew/opt/python@3.14/bin/python3.14 /private/tmp/h3-u4-authoritative-uizkm1rc/conversion/driver.py success /private/tmp/h3-u4-authoritative-uizkm1rc/conversion/ane.mlpackage < /dev/null`
- Exit status: `0`
- Sanitized output: `{"exists": true, "temps": 0}`
- Post-state: complete package published without prompt
- Next invocation / compensation result: same headless command reruns successfully
- Mechanism check: closed stdin plus exit 0 proves noninteractive behavior
