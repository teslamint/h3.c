# Roadmap

## ANE acceleration evidence gates

Owner: Human operator on target Apple Silicon.

Statuses: `blocked`, `ready`, `in-progress`, `passed`, `failed`.

Qualification and claim gates 2–6 remain sequential: a later gate cannot pass
until every earlier one passes. Tooling gates 1 and 7 can close independently,
but neither authorizes Core ML output or an ANE claim. Broader ANE blocks and
default-on execution cannot begin until strict qualification and observed
placement pass. Procedures are in `docs/ane-acceleration.md`; commit only
sanitized summaries under `docs/evidence/ane-acceleration/<date>/`.

| Order | Status | Priority | Gate | Acceptance evidence |
|---:|---|---|---|---|
| 1 | passed | P1 | Add stage-specific qualification diagnostics | Fresh `make h3_ane_tool_tests && python3 -m unittest discover -s tests -p 'test_ane_tools.py'` passed 66 tests; `make h3_ane_tests h3_ane_qualification h3_ane_integration_probe` passed; actual-Metal `./h3_ane_tests` passed. Writable failures carry the closed stage/code context, result-publication failure falls back to stderr, and failures publish no receipt. |
| 2 | blocked | P1 | Qualify the fixed FL2VA block on the target machine | Fresh strict real target reached `parity/parity_bounds_failed`: `max_abs=0.19216197729110718`, `relative_l2=0.038400878187031535`, and `receipt:null`. Passing requires matching digests, `max_abs < 0.002`, and `relative_l2 < 0.02`. |
| 3 | blocked | P1 | Observe Neural Engine execution | Sanitized Instruments summary shows Neural Engine activity overlapping the prediction interval; compute-plan eligibility alone does not pass. |
| 4 | blocked | P2 | Measure alternating latency | At least 20 complete A/B pairs; paired 95% confidence lower bound above zero; median transfer-inclusive improvement at least 5%. |
| 5 | blocked | P2 | Measure process memory | Matched `/usr/bin/time -l` summaries show Core ML maximum RSS growth no greater than 5%. |
| 6 | blocked | P2 | Measure energy independently | Sanitized named counter and unit show at least 5% paired-median improvement on the same workload. |
| 7 | passed | P2 | Add a one-command conversion integration gate | Fresh `H3_ANE_TRACE=1 make h3_ane_integration_test` passed package generation, compilation, production metadata/schema loading, and inventory `441/149/149/0` (total/nonconstant/Neural-Engine-supported/CPU-only-and-unknown, both zero) with synthetic `parity:null` and `receipt:null`. The real `make h3_ane_shadow_measurement_test` also passed only the non-authorizing shadow profile (`authority:false`, `receipt:null`); strict receipt publication remains gate 2. |

Evidence policy: commit bounded text/JSON/CSV summaries smaller than 1 MiB with
chip class, OS/tool versions, relative artifact identifiers, digests, timings,
errors, RSS, and energy values. Keep raw Instruments traces, compiled models,
safetensors, media, absolute private paths, serials/UUIDs, and large logs local.
