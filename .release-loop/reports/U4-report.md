# U4 Report: DONE_WITH_CONCERNS

- Unit: U4 conversion, qualification, and benchmark tooling
- TDD status: Python converter/analyzer RED observed, then 9 tests GREEN.
- Native tooling RED observed (`make h3_ane_tool_tests` initially had no rule),
  then qualification and benchmark fixture binaries were implemented.
- Current implementation: converter/analyzer scripts, native qualification and
  benchmark tools, Make targets, and 11 always-on tests are GREEN.
- Current matrix evidence inventory: 24/24 records (Convert, Compile, Qualify,
  Record benchmark; six outcomes each) under `.release-loop/evidence/U4/`.
- Verification:
  - `python3 -m unittest tests/test_ane_tools.py`: 11 passed.
  - `make h3_ane_qualification h3_ane_bench h3_ane_tool_tests`: passed with
    strict C warnings enabled.
  - `make h3_ane_tests && ./h3_ane_tests`: passed.
  - `make -j8`: passed.
  - `make test` with actual Metal access: passed (`1768` core checks, native
    AudioVAE Metal primitives passed, unavailable private fixtures skipped).
  - pinned `uv run --python 3.12 --with coremltools==9.0 --with numpy==2.3.2
    --with safetensors==0.6.2 ... --help`: passed.
  - real source conversion: passed, source digest
    `ad7b9b6432fc3c31c095bd6918c47ea5d6d0f145f4fae33fd46e0fc2738ce163`.
  - `xcrun coremlcompiler compile`: passed and produced a `.mlmodelc`.
  - real qualification: explicit failed result retained at
    `.release-loop/evidence/U4/real-qualification.json`; reason is
    `ANE backend is unavailable`, and no passing receipt exists.
  - `git diff --check`: passed.
- Concern: real placement/qualification could not pass on the current compiled
  graph/runtime. This is an explicit measurement result, not a synthetic test
  failure, and correctly leaves the default-off harness unauthorized.
- Blockers: none for U4 harness delivery; no ANE performance claim is permitted.
