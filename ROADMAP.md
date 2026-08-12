# Roadmap

## ANE acceleration evidence gates

Owner: Human operator on target Apple Silicon.

Statuses: `blocked`, `ready`, `in-progress`, `passed`, `failed`.

Later gates remain `blocked` until every earlier gate is `passed`. Broader ANE
blocks and default-on execution cannot begin until both qualification and
observed placement pass. Procedures are in `docs/ane-acceleration.md`; commit
only sanitized summaries under `docs/evidence/ane-acceleration/<date>/`.

| Order | Status | Priority | Gate | Acceptance evidence |
|---:|---|---|---|---|
| 1 | ready | P1 | Add stage-specific qualification diagnostics | A writable failed RESULT identifies the first stable stage/code from setup through publication; an unwritable RESULT reports publication failure on stderr; table-driven tests cover the closed taxonomy; no receipt is written on failure. |
| 2 | blocked | P1 | Qualify the fixed FL2VA block on the target machine | Passing receipt with matching model/source digests, `max_abs < 0.002`, and `relative_l2 < 0.02`. |
| 3 | blocked | P1 | Observe Neural Engine execution | Sanitized Instruments summary shows Neural Engine activity overlapping the prediction interval; compute-plan eligibility alone does not pass. |
| 4 | blocked | P2 | Measure alternating latency | At least 20 complete A/B pairs; paired 95% confidence lower bound above zero; median transfer-inclusive improvement at least 5%. |
| 5 | blocked | P2 | Measure process memory | Matched `/usr/bin/time -l` summaries show Core ML maximum RSS growth no greater than 5%. |
| 6 | blocked | P2 | Measure energy independently | Sanitized named counter and unit show at least 5% paired-median improvement on the same workload. |
| 7 | blocked | P2 | Add a one-command conversion integration gate | Pinned command proves package generation, compilation, runtime metadata, graph/reference parity, and atomic receipt publication end to end. |

Evidence policy: commit bounded text/JSON/CSV summaries smaller than 1 MiB with
chip class, OS/tool versions, relative artifact identifiers, digests, timings,
errors, RSS, and energy values. Keep raw Instruments traces, compiled models,
safetensors, media, absolute private paths, serials/UUIDs, and large logs local.
