# U5 Documentation Report

Status: DONE

Initial commit: `cc7eb9e`

Review-fix commit: `fec195b`

## Review round 1 corrections

- Defined `ANE_INTEGRATION_WORK` and derived the strict compiled model as
  `H3_ANE_STRICT_MODEL="$ANE_INTEGRATION_WORK/visual-block.mlmodelc"`; the
  documented default resolves exactly to
  `/private/tmp/h3-ane-integration/visual-block.mlmodelc`.
- Added the strict direct-qualification command and changed latency, RSS, and
  conditional energy commands to use only `H3_ANE_STRICT_MODEL` plus its
  receipt. The shadow artifact is explicitly forbidden as a substitute.
- Defined `ANE_SHADOW_WORK` and the existing compiled shadow artifact as
  `H3_ANE_SHADOW_MODEL="$ANE_SHADOW_WORK/visual-block.mlmodelc"` before direct
  `--shadow-only` use.
- Added an executable `xcrun xctrace record` command using the installed
  `Core ML` template. It wraps the same real first frame, prompt, and geometry
  as the shadow run, sets `H3_ANE_SHADOW=1`, uses the explicit shadow model, and
  writes to `/private/tmp/h3-ane-shadow-placement.trace` only when absent.
- Kept shadow tracing placement-only and non-authorizing: Core ML output is
  discarded, Metal output is returned, and no receipt is created.
- Added a separate strict-receipt energy command using the installed `Core ML`
  template and `Neural Engine` instrument. It remains conditional on a passing
  strict receipt and a unit-bearing exported energy counter.
- `xcrun xctrace list templates` confirmed `Core ML`; `xcrun xctrace list
  instruments` confirmed `Neural Engine`.
- One-second disposable trace dry runs succeeded for both `Core ML` alone and
  `Core ML` plus `Neural Engine`; both temporary traces were removed.
- Extracted all 12 shell blocks and passed `zsh -n`; qualifier/benchmark/H3 help
  surfaces continue to match every documented flag.
- Review-fix `git diff --check` passed; protected spec, plan, deviations, public
  header, README, and ROADMAP remain unchanged in this round.

## Documentation delivered

- Replaced the stale backend-unavailable summary with the current real artifact
  evidence: inventory `441/149/149/0`, strict
  `parity/parity_bounds_failed`, `max_abs=0.19216197729110718`,
  `relative_l2=0.038400878187031535`, and no receipt.
- Documented `shadow-measurement-v1` as finite exploratory measurement only:
  `max_abs < 0.25`, `relative_l2 < 0.05`, `authority:false`,
  `receipt:null`, discarded Core ML output, and Metal-authoritative output.
- Preserved strict `0.002 / 0.02` qualification as the exclusive receipt and
  non-shadow authority path.
- Documented the closed diagnostic taxonomy, mode-dependent integration schema,
  fixed F32 NDHWC `[1,1,256,256,128]` graph, two-pass 4096-operation and
  64-level traversal limits, pinned Core ML Tools environment, local-artifact
  policy, receipt binding, and rejection of every compiled-model symlink.
- Documented the synthetic, strict-real, and shadow Make targets plus direct
  qualifier `--shadow-only` use and exact missing-weight prerequisite behavior.
- Documented receipt-directory quarantine preflight failure as no measurement,
  exit 2, `measurement_started:false`, `authority_state:"unchanged"`,
  `authority:false`, `receipt_path:null`, and no accepted evidence.
- Added a real 256-by-256 `FIRST_FRAME` prerequisite and matched Metal baseline
  and shadow generation commands. The baseline explicitly unsets all ANE
  variables; both commands use the same prompt and generation geometry.
- Kept `eligible`, `preferred`, and `observed Neural Engine` distinct. No
  placement, latency, process-memory, energy, production-equivalence, or
  acceleration claim was added.
- Updated ROADMAP gate 1 and tooling gate 7 from fresh evidence. Strict gate 2
  remains blocked, so gates 3-6 remain blocked.

## Fresh verification

- `python3 -m unittest discover -s tests -p 'test_ane_tools.py'`: 69 passed.
- `make h3_ane_tool_tests`: passed.
- `make h3_ane_qualification h3_ane_integration_probe h3_ane_bench`: passed.
- `./h3_ane_qualification --help`: passed.
- `./h3_ane_bench --help`: passed.
- `python3 scripts/run_ane_integration.py --help`: passed.
- `python3 scripts/analyze_ane_benchmark.py --help`: passed.
- Pinned uv converter `--help` command: passed.
- Actual-Metal `./h3_ane_tests`: passed.
- Fresh `H3_ANE_TRACE=1 make h3_ane_integration_test`: passed with inventory
  `441/149/149/0`, `parity:null`, and `receipt:null`.
- Fresh real shadow target: passed with `authority:false`, `receipt:null`, the
  exact inventory above, and metrics `0.19216197729110718 /
  0.038400878187031535`.
- Fresh strict real target: failed closed as expected with
  `parity/parity_bounds_failed`, the same metrics, `receipt:null`, and no
  receipt sidecar.
- Both real Make targets without `H3_ANE_WEIGHT_DIR`: exited 2 with their exact
  prerequisite messages.
- H3 help exposes every documented first-frame and generation-geometry flag.
- The documented ffprobe expression accepted a disposable real 256-by-256 PNG.
- Both JSON examples parsed with `json.loads`.
- Required-term and forbidden-claim scans passed.
- `git diff --check`: passed.
- Protected spec, plan, deviation, and public `h3.h` diffs: empty.
- Documentation diff scope before commit: `README.md`, `ROADMAP.md`, and
  `docs/ane-acceleration.md` only.

## Validation boundary

The full baseline/shadow video-generation pair was not run because the operator
must supply the documented real 256-by-256 first-frame conditioning image.
Command syntax, H3 flags, shared geometry, ANE-variable removal, and the exact
ffprobe prerequisite were verified. Strict-only benchmark and Instruments
commands remain intentionally gated by a passing strict receipt and operator
measurement setup; the current artifact has no strict receipt.

No product code, public header, sealed artifact, retained evidence, `.omx/`, or
unrelated cache was changed.

## Final branch review closure

- Exact source commit: `17ef0f1dc8436de56c689cd2f3b5f9445ee738af`.
- Closed first-failure diagnostic context, strict receipt preflight, coordinator reuse authority preservation, and sealed taxonomy were revalidated by 69 Python tests, strict Clang analysis, actual-Metal ANE tests, and fresh isolated synthetic/real runs.
