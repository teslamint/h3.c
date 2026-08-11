---
schema: plan/v1
title: Experimental Apple Neural Engine Acceleration
type: feat
status: draft
date: 2026-08-11
execution: code
origin: docs/specs/2026-08-11-ane-acceleration-design.md
deepened: true
---

# Experimental Apple Neural Engine Acceleration Plan

## Goal

Implement a default-off, fingerprint-bound Core ML measurement harness for the
fixed FL2VA visual-encoder level-0/block-0 residual block. Preserve Metal as the
default and fallback, qualify artifacts offline, and prevent ANE performance
claims unless placement and quantitative evidence exist.

## Architecture notes

- Keep the public `h3.h` API unchanged. New Core ML behavior is private to the
  video encoder. `H3_ANE_MODEL=/absolute/path/model.mlmodelc` enables qualified
  mode; `H3_ANE_SHADOW=1` selects shadow mode; `H3_ANE_TRACE=1` prints contract,
  compute-plan, preferred-device, timing, and fallback diagnostics. The receipt path is fixed as
  `<model.mlmodelc>.qualification.json`; no second path setting exists.
- Implement the bridge in Objective-C `.m`, not Objective-C++, so existing
  Objective-C flags remain valid. Link Core ML without changing C compiler mode.
- Core ML executes only on macOS 14.4+ with
  `MLComputeUnitsCPUAndNeuralEngine`. Every non-constant operation must list the
  Neural Engine as supported in `MLComputePlan`; otherwise select Metal.
- Bind an artifact to active weights with a SHA-256 digest over sorted tensor
  name, dtype, shape, and raw payload bytes. Bind qualification to the compiled
  model with a second deterministic directory digest and a receipt.
- Treat shadow and non-shadow differently. Shadow mode always adopts Metal
  output and may inspect an unqualified artifact. Non-shadow requires a passing
  receipt and uses only online structural validation: contract, digests, exact
  shape/dtype/count, prediction status, and finite output.
- Keep Core ML input/output separate from Metal storage until online validation
  succeeds. On any failure, call the unchanged Metal block from the immutable
  original input.
- Use Core ML Tools only through
  `uv run --python 3.12 --with coremltools==9.0 --with numpy==2.3.2 --with safetensors==0.6.2`
  developer commands. No Python dependency enters the C runtime or default
  build.
- The converted ML Program must reproduce 32-group normalization with epsilon
  `1e-6`, NDHWC activation layout, OIDHW weight conversion, two-front temporal
  zero padding, reflected one-pixel spatial padding, two 128-to-128 Conv3D
  operations, SiLU, and residual add.

## Assumption Recheck

| Approved claim | Fresh command | Observed at | Result | Outcome |
|---|---|---|---|---|
| Objective-C and Apple compute frameworks are already used. | `sed -n '1,20p' Makefile` | `2026-08-11T14:08:16Z` | Objective-C sources and Metal/MPS/MPSGraph framework links remain present. | match |
| Level 0/block 0 remains an isolated 128-channel residual block. | `sed -n '13,27p;286,321p;419,471p' h3_video_encoder.c` | `2026-08-11T14:08:16Z` | Dimensions, weight prefix construction, and block operations are unchanged. | match |
| Existing MPSGraph execution uses nil descriptors. | `sed -n '1538,1545p;1919,1925p;2392,2398p' h3_gpu.m` | `2026-08-11T14:08:16Z` | SDPA, Conv3D, and linear still pass `executionDescriptor:nil`. | match |
| The private 256 fixture is absent. | `test -f misc/fixtures/h3_real_video_encoder_256.safetensors` | `2026-08-11T14:08:16Z` | Exit 1; the fixture remains absent and the end-to-end test remains conditional. | match |
| FL2VA source weights are locally available. | `test -f MiniMax-H3/FL2VA/video_vae/source/model.safetensors && du -sh MiniMax-H3/FL2VA/video_vae/source` | `2026-08-11T14:08:16Z` | Source weights exist; directory is about 9.7 GiB. | match |
| SDK and trace tooling support the floor. | `xcrun --show-sdk-version && command -v xctrace` | `2026-08-11T14:08:16Z` | SDK 26.5 and `/usr/bin/xctrace` are available. | match |
| Conversion packages are not globally installed. | `python3 -c 'import coremltools, numpy, safetensors'` | `2026-08-11T14:08:16Z` | Exit 1; isolated conversion environment remains required. | match |

## File structure

### Core ML runtime boundary

- Create `h3_ane.h`: opaque handle, fixed contract constants, status/reason
  enums, stats, create/predict/free functions, and platform-neutral test seams.
- Create `h3_ane.m`: Core ML load/configuration, metadata and receipt validation,
  compute-plan eligibility, prediction, timing, finite-output checks, and
  diagnostics.
- Create `h3_ane_receipt.c` and `h3_ane_receipt.h`: portable deterministic
  SHA-256 directory/tensor digest and strict receipt parsing used by runtime and
  tests.

### Video encoder integration

- Modify `h3_video_encoder.c`: initialize the optional handle, dispatch only
  level 0/block 0 at `[1,1,256,256,128]`, support shadow adoption rules, and
  fall back without input mutation.
- Modify `h3_video_encoder.h`: include `h3_ane.h` and add
  `h3_ane_stats ane_stats` to `h3_video_latent`; preserve function signatures and
  the public `h3.h` generation interface.
- Create `h3_ane_dispatch.c` and `h3_ane_dispatch.h`: pure C selection/adoption
  seam with an injected Metal callback that accepts the original
  `h3_gpu_tensor *`; fallback therefore calls the existing Metal path without a
  GPU-to-host conversion or replacement input.

### Offline artifact and measurement tooling

- Create `scripts/convert_ane_visual_block.py`: read selected safetensors, build
  exact ML Program semantics, embed contract metadata, and emit source digest.
- Create `tests/qualify_ane.c`: native `h3_ane_qualification` executable that
  loads active FL2VA weights, runs the exact Metal block and Core ML from one
  deterministic input, and emits metrics for receipt creation.
- Create `scripts/analyze_ane_benchmark.py`: validate complete alternating sample
  sets and calculate paired median and deterministic bootstrap interval.
- Create `tests/bench_ane.c`: matched Metal/Core ML/shadow benchmark JSON output.

### Tests, build, and documentation

- Create `tests/test_ane.c`: receipt/digest validation, opt-in behavior, failure
  injection, structural checks, and fallback equivalence.
- Modify `Makefile`: Core ML framework, new objects, test/qualification/benchmark
  targets, dependency declarations, and clean rules.
- Modify `README.md`: default-off status, environment variables, conversion,
  qualification, benchmark, trace, fallback, and claim boundaries.

## Scenario coverage map

| Scenario | Unit chain | Walking evidence |
|---|---|---|
| S1 zero-change baseline | U5 | U5 integration scenario runs the existing real encoder target under a documented Instruments command when its fixture is installed. |
| S2 opt into experimental block | U1 → U2 → U3 → U4 | U4 integration scenario converts, qualifies, loads, and executes the fixed block with explicit `H3_ANE_MODEL`. |
| S3 safe fallback | U1 → U2 → U3 | U3 integration scenario forces each backend failure and compares output with a fresh Metal-only run. |
| S4 reproducible comparison | U3 → U4 → U5 | U4 produces complete A/B JSON; U5 analyzes it and documents trace and memory evidence. |

## Implementation Units

## U1: Receipt, digest, and contract foundation
Execution note: test-first
Files:
  Create: h3_ane_receipt.c, h3_ane_receipt.h, tests/test_ane.c
  Modify: Makefile
  Test: tests/test_ane.c
Interfaces:
  Consumes: file paths, ordered tensor descriptors, raw tensor byte ranges
  Produces: `typedef enum { H3_ANE_DTYPE_F32 = 1 } h3_ane_dtype`; `h3_ane_contract { uint32_t version; char variant[16]; uint32_t block_level; uint32_t block_index; char weight_prefix[64]; h3_ane_dtype boundary_dtype; uint32_t shape[5]; char source_sha256[65]; }`; `h3_ane_receipt { uint32_t version; char model_sha256[65]; char source_sha256[65]; char test_vector[32]; char qualified_at[32]; double max_abs; double relative_l2; int passed; }`; `int h3_ane_sha256_directory(const char *path, char out[65], char *error, size_t error_size)`; `int h3_ane_sha256_tensors(const h3_weight_store *store, const char *const *names, size_t name_count, char out[65], char *error, size_t error_size)`; `int h3_ane_receipt_load(const char *path, h3_ane_receipt *out, char *error, size_t error_size)`; `int h3_ane_receipt_validate(const h3_ane_contract *, const h3_ane_receipt *, const char model_sha256[65], char *error, size_t error_size)` rejects unless `passed == 1`, `max_abs < 0.002`, and `relative_l2 < 0.02`
Test scenarios:
  happy: a canonical receipt with matching compiled-directory and source-tensor digests validates
  edge: directory enumeration order and JSON field order do not change the canonical digest/parsed contract
  error: missing fields, unknown versions, path traversal, malformed hex, mismatched variant/digest, failed status, `max_abs >= 0.002`, `relative_l2 >= 0.02`, and changed compiled bytes are rejected
  integration: a synthetic compiled-model directory and receipt validate through the same API used by the Core ML bridge, Covers S3
Steps:
  1. Add failing digest/receipt tests with temporary directories and deterministic byte fixtures.
  2. Run `make h3_ane_tests && ./h3_ane_tests`; confirm link or assertion failure because receipt support is absent.
  3. Implement strict size-bounded parsing and CommonCrypto SHA-256 helpers without a new dependency; never follow symlinks outside the model directory.
  4. Add Makefile target/dependency/clean entries and rerun the focused test plus `make test`.
  5. Commit: `feat(ane): Add qualified model receipt contract`
Acceptance: `make h3_ane_tests && ./h3_ane_tests` passes and `git diff --check` is clean.

## U2: Optional Core ML runtime bridge
Execution note: test-first
Files:
  Create: h3_ane.h, h3_ane.m
  Modify: Makefile, tests/test_ane.c
  Test: tests/test_ane.c
Interfaces:
  Consumes: `h3_ane_contract`, compiled-model directory, fixed sidecar receipt, contiguous F32 `[1,1,256,256,128]`
  Produces: `typedef enum { H3_ANE_REASON_NONE, H3_ANE_REASON_DISABLED, H3_ANE_REASON_OS, H3_ANE_REASON_CONTRACT, H3_ANE_REASON_FINGERPRINT, H3_ANE_REASON_RECEIPT, H3_ANE_REASON_ELIGIBILITY, H3_ANE_REASON_LOAD, H3_ANE_REASON_PREDICTION, H3_ANE_REASON_SHAPE, H3_ANE_REASON_DTYPE, H3_ANE_REASON_NONFINITE } h3_ane_reason`; device bit values `H3_ANE_DEVICE_CPU = 1u << 0`, `H3_ANE_DEVICE_GPU = 1u << 1`, `H3_ANE_DEVICE_NEURAL_ENGINE = 1u << 2`; `h3_ane_operation_usage { char name[96]; int is_constant; uint32_t supported_devices; uint32_t preferred_device; }`; opaque `h3_ane`; `h3_ane *h3_ane_create(const char *model_path, const h3_ane_contract *contract, int shadow, char *error, size_t error_size)`; `int h3_ane_is_shadow(const h3_ane *ane)`; `int h3_ane_predict(h3_ane *ane, const float *input, size_t input_count, float *output, size_t output_count, h3_ane_stats *stats, char *error, size_t error_size)`; `void h3_ane_free(h3_ane *ane)`; `h3_ane_stats { double load_seconds; double input_seconds; double prediction_seconds; double output_seconds; uint64_t attempts; uint64_t predictions; uint64_t fallbacks; h3_ane_reason last_reason; uint32_t preferred_device; int shadow; }`
Test scenarios:
  happy: a test seam reports eligible operations and a structurally valid prediction from separate output storage
  edge: default environment performs no Core ML load; shadow mode loads without a receipt but marks output non-adoptable; `H3_ANE_TRACE=1` reports named operation eligibility and preferred device
  error: macOS below 14.4, load failure, receipt failure, any non-constant operation lacking Neural Engine support, prediction exception, wrong count/dtype, and non-finite output return stable failure reasons
  integration: a synthetic backend seam exercises load, eligibility, prediction, and teardown without requiring private weights, Covers S2
Steps:
  1. Extend focused tests using `h3_ane_test_backend { int (*load)(void *); int (*plan)(void *, h3_ane_operation_usage *, size_t *); int (*predict)(void *, const float *, size_t, float *, size_t); void (*free)(void *); void *opaque; }` installed only by `h3_ane_test_set_backend(const h3_ane_test_backend *)` when compiled with `H3_ANE_TESTING`; assert default-off, qualification, compute-plan, trace, and prediction behavior.
  2. Run `make h3_ane_tests && ./h3_ane_tests`; confirm undefined bridge APIs.
  3. Implement the Objective-C bridge with availability guards, `CPUAndNeuralEngine`, strict all-operation eligibility, separate output storage, autorelease pools, and exception-to-error conversion.
  4. Link Core ML, rerun focused tests, then `make -j8` and `make test`.
  5. Commit: `feat(ane): Add optional Core ML runtime bridge`
Acceptance: default builds succeed, focused tests pass, and an unset `H3_ANE_MODEL` produces zero model-load attempts.

## U3: Safe visual-encoder dispatch and fallback
Execution note: characterization-first
Files:
  Create: h3_ane_dispatch.c, h3_ane_dispatch.h
  Modify: h3_video_encoder.c, h3_video_encoder.h, tests/test_ane.c, Makefile
  Test: tests/test_ane.c, tests/test_real_video_encoder.c
Interfaces:
  Consumes: existing `run_block`, `encoder_context`, `h3_ane_predict`, level/block indices, active weight store; `typedef h3_gpu_tensor *(*h3_ane_metal_block_fn)(void *opaque, h3_gpu_tensor *original_input, char *error, size_t error_size)`
  Produces: `h3_gpu_tensor *h3_ane_dispatch_gpu_block(h3_ane *ane, h3_gpu *gpu, h3_gpu_tensor *original_input, size_t count, h3_ane_metal_block_fn metal, void *metal_opaque, h3_ane_stats *stats, char *error, size_t error_size)` derives shadow mode only from `h3_ane_is_shadow(ane)`; on fallback it calls `metal(metal_opaque, original_input, ...)` with pointer identity preserved; on Core ML success it alone reads F32 input and creates a new GPU output; shadow calls both and returns Metal; `int h3_video_encoder_block0_qualification(const char *weight_directory, const char *model_path, const float *input, size_t input_count, float *metal_output, float *coreml_output, size_t output_count, char *error, size_t error_size)` for the native qualification executable
Test scenarios:
  happy: qualified exact-shape candidate adopts Core ML output only in non-shadow mode
  edge: other levels, blocks, frame counts, spatial sizes, disabled mode, and handle-owned shadow mode use/adopt Metal exactly as specified; no caller-supplied second shadow flag exists
  error: every bridge failure reason leaves original input unchanged and matches a fresh Metal-only block execution
  integration: use deterministic injected Core ML failures and a fake Metal callback in every checkout; assert the callback receives the exact original `h3_gpu_tensor *` and its result is adopted; optionally repeat through the full real encoder when its fixture is installed, Covers S3
Steps:
  1. Characterize existing level-0/block-0 output and ownership using a small deterministic test seam around the block.
  2. Add failing dispatch/fallback tests and confirm Core ML output is never adopted before successful online validation.
  3. Initialize the optional handle once per encoder run, calculate/cache the active tensor fingerprint, and dispatch only the exact candidate shape.
  4. Preserve original input until adoption, implement shadow mode and stable stats, then run focused, real-if-present, and full tests.
  5. Commit: `feat(ane): Add safe visual encoder fallback dispatch`
Acceptance: `make h3_ane_tests && ./h3_ane_tests && make test` passes; the optional real encoder target passes when its fixture exists.

## U4: Conversion, qualification, and benchmark tooling
Execution note: test-first
Files:
  Create: scripts/convert_ane_visual_block.py, scripts/analyze_ane_benchmark.py, tests/qualify_ane.c, tests/bench_ane.c, tests/test_ane_tools.py
  Modify: Makefile
  Test: tests/test_ane_tools.py, tests/bench_ane.c
Interfaces:
  Consumes: FL2VA safetensors, fixed block contract, compiled Core ML directory, native shadow executable, alternating sample JSON
  Produces: `ane-visual-block.mlpackage`; compiled `ane-visual-block.mlmodelc` via `xcrun coremlcompiler compile`; `h3_ane_qualification --model WEIGHT_DIR --coreml-model MODEL.mlmodelc --output RESULT.json` invalidates any old sidecar first, performs shadow parity, atomically writes RESULT as `{schema:"h3-ane-qualification/v1", status:"passed"|"failed", model_sha256:string, source_sha256:string, test_vector:string, qualified_at:string, max_abs:number, relative_l2:number, receipt_path:string, failure_reason:string|null}`, and atomically creates `<MODEL.mlmodelc>.qualification.json` only on pass with the same digest/vector/time/metric fields; `h3_ane_bench --backend metal|coreml|ab --coreml-model PATH --warmup N --pairs N --output PATH`; `ab` performs two warm-ups per backend by default and alternates AB for even pairs, BA for odd pairs; benchmark JSON fields `{schema, mode, warmup, pairs, placement_summary, samples:[{pair,order,selected_backend,metal_seconds,coreml_input_seconds,coreml_prediction_seconds,coreml_output_seconds,coreml_total_seconds,max_abs,relative_l2}], peak_rss_bytes}`; `scripts/analyze_ane_benchmark.py INPUT`
Test scenarios:
  happy: synthetic tiny weights exercise layout/padding conversion, receipt creation, complete alternating samples, and positive bootstrap analysis
  edge: OIDHW-to-Core-ML layout, two-front temporal zero padding, reflected spatial padding, group count 32, epsilon `1e-6`, deterministic seed, and exactly zero omitted post-warm samples are pinned
  error: missing packages, wrong tensor names/shapes, unsupported conversion op, failed max-absolute `2e-3` or relative-L2 `0.02` parity, changed compiled digest, incomplete/nonalternating samples, and fewer than 20 pairs fail with no passing receipt
  integration: pinned Python 3.12 environment converts the real block, `xcrun coremlcompiler compile` creates the runtime directory, native `h3_ane_qualification` writes both metrics and a passing sidecar, and `h3_ane_bench --backend ab --warmup 2 --pairs 20` emits complete alternating A/B data with placement/parity/timing fields, Covers S2, Covers S4
Steps:
  1. Add Python tests for tensor selection/layout, metadata, atomic receipt behavior, sample validation, paired statistic sign, and deterministic bootstrap.
  2. Run `python3 -m unittest tests/test_ane_tools.py`; confirm missing tool modules/functions.
  3. Implement conversion and analysis with lazy third-party imports so analysis tests need only the standard library; implement `h3_ane_qualification`, `h3_ane_bench`, and exact Makefile targets.
  4. Run unit tests; run `uv run --python 3.12 --with coremltools==9.0 --with numpy==2.3.2 --with safetensors==0.6.2 scripts/convert_ane_visual_block.py --help`; convert to `.mlpackage`; run `xcrun coremlcompiler compile <package> <output-directory>`; run `make h3_ane_qualification h3_ane_bench`; then attempt real qualification and retain failure or pass evidence in the ledger.
  5. Commit: `feat(ane): Add conversion and benchmark tooling`
Acceptance: tool unit tests and native focused tests pass; conversion failure cannot leave a passing receipt; real qualification status is explicit.

## U5: Operator workflow and evidence boundaries
Execution note: skip-test-first
Files:
  Modify: README.md
  Create: docs/ane-acceleration.md
  Test: n/a — documentation commands are verified by `--help`, build targets, or conditional dry runs
Interfaces:
  Consumes: implemented environment variables, Make targets, tool CLI, receipt schema, benchmark output
  Produces: end-to-end baseline, conversion, qualification, shadow, benchmark, memory, Instruments, and claim workflow; latency claim requires at least 20 pairs, paired Metal-minus-Core-ML 95% bootstrap lower bound greater than zero, and median transfer-inclusive improvement at least 5%; process-memory claim compares `/usr/bin/time -l` maximum resident set size and permits at most 5% growth; energy claim names one exported Instruments counter/unit and requires at least 5% paired-median improvement
Test scenarios:
  happy: a developer with local weights follows the documented commands from Metal baseline through qualification
  edge: absent private fixture and absent conversion packages have explicit skip/install-isolated behavior
  error: docs state that build success, configuration, compute-plan eligibility, CPU/mixed placement, or an unqualified model cannot support an ANE claim
  integration: execute every `--help`/build command and validate conditional prerequisites; document the exact Instruments baseline for current MPSGraph, Covers S1, Covers S4
Steps:
  1. Document default-off behavior, OS floor, model identity, receipt, online/offline validation, and fallback reasons.
  2. Document isolated conversion, qualification, shadow, A/B, `/usr/bin/time -l`, Instruments, and independent latency/energy/memory claim gates.
  3. Run documented `--help` and build commands, scan for stale Objective-C++ or ANE-guarantee language, and run `git diff --check`.
  4. Commit: `docs(ane): Document the acceleration experiment`
Acceptance: commands match implemented interfaces; `scripts/analyze_ane_benchmark.py` enforces the 20-pair/CI/5% latency rule; documented `/usr/bin/time -l ./h3_ane_bench --backend metal --pairs 20 --output .release-loop/evidence/ane-metal.json` and `/usr/bin/time -l ./h3_ane_bench --backend coreml --coreml-model "$H3_ANE_MODEL" --pairs 20 --output .release-loop/evidence/ane-coreml.json` commands cover process memory; Instruments instructions require an exported named counter with 5% paired-median improvement; a reviewer can distinguish harness readiness from verified ANE placement/performance.

## Mutation/failure-state matrix

| Transition | Pre-state | Action | Expected post-state | Success | Forced failure | Rerun | Rollback/compensation | Headless | Cancellation/abort | Unit / evidence owner |
|---|---|---|---|---|---|---|---|---|---|---|
| Convert source weights to model package | Existing immutable safetensors; destination absent | Build exact fixed-block ML Program into a temporary sibling path, then atomically rename | Complete model package with contract metadata; no receipt | Rename completes and package digest is readable | Inject unsupported tensor shape in an isolated copy; command exits nonzero and removes temporary path | Existing matching package is replaced only through a new temporary path; no append behavior | Delete unqualified package; source weights remain untouched | Noninteractive CLI returns structured exit code and stderr | SIGINT handler removes temporary path; stale temp is never loadable because runtime requires receipt | U4 / `.release-loop/evidence/U4/conversion/` |
| Compile model package | Complete `.mlpackage`; compiled destination absent | Run `xcrun coremlcompiler compile PACKAGE OUTPUT_DIR` into a new output directory | Loadable `.mlmodelc`; no qualification receipt | Compiler exits zero and runtime metadata is readable | Compile a malformed isolated package; destination is absent or removed | Remove previous unqualified output and compile into a fresh directory | Delete compiled directory; package remains reproducible | `xcrun` is noninteractive and returns its exit code | Cancellation removes partial output before qualification; receipt is absent | U4 / `.release-loop/evidence/U4/compile/` |
| Qualify compiled model | Compiled model exists; receipt may be absent or valid | First atomically rename any old receipt to a non-loadable `.invalid` audit file, then run deterministic shadow comparison and atomically create a new receipt only on pass | Exactly one passing receipt bound to current model/source digests | Bounds `max_abs < 0.002` and `relative_l2 < 0.02` pass and new receipt says `passed` | Inject output perturbation; old receipt is already invalidated and no passing receipt is written | Every rerun invalidates the prior receipt before testing and requires a new pass | Delete/rename receipt to disable non-shadow execution | CLI emits JSON result and stable exit code | SIGINT removes receipt temp; prior receipt remains `.invalid` and runtime cannot load it | U4 / `.release-loop/evidence/U4/qualification/` |
| Execute experimental prediction | Qualified model/receipt and immutable Metal input exist | Validate receipt/plan, predict to separate storage, structurally validate, then adopt | Core ML output adopted only after all checks | Stats name Core ML and output is finite/exact count | Fake backend injects each failure before adoption; unchanged input runs Metal | Each invocation revalidates model directory digest and starts from request input | Metal is compensation; no persistent model state is mutated | Environment-controlled path emits stable status without prompts | Process cancellation may abandon request output; no durable state transition exists and source/model remain unchanged | U2/U3 / `.release-loop/evidence/U3/` |
| Record benchmark evidence | Qualified model; evidence destination absent | Alternate warm Metal/Core ML samples and atomically write complete JSON | Complete ordered sample set | 20+ pairs and analyzer accepts schema/order | Inject interruption after an odd sample; temporary JSON is rejected/not renamed | New run writes a new complete artifact rather than appending | Delete incomplete temp; benchmark has no product-state effect | CLI requires all inputs as flags/environment and prints progress to stderr | SIGINT closes/removes temp; no partial final JSON | U4 / `.release-loop/evidence/U4/benchmark/` |

## Carry-forward trigger audit

No durable carry-forward tracker in this repo; no trigger audit possible.

## Deferred to Follow-Up Work

- Full DiT, text encoder, audio, decoder, multiple visual blocks, and dynamic
  shapes remain separate projects because each requires a new graph boundary and
  independent placement/parity evidence.
- Production-default ANE selection is deferred until real placement, quality,
  latency, energy, and memory evidence passes on supported target machines.
- Bundling generated Core ML artifacts is deferred because model licensing,
  repository size, and release distribution are outside this experiment.

## Open unknowns

### Planning-time

None. Product behavior, safety gates, OS floor, compute policy, model identity,
and release outcome are fixed by the approved spec.

### Implementation-time

- Exact Core ML metadata accessor names and `MLComputePlan` traversal calls must
  match SDK 26.5 headers while preserving the all-nonconstant-operation rule.
- The smallest Core ML graph expression for temporal-zero plus spatial-reflect
  padding must be selected by conversion experiments; inability to express the
  approved semantics blocks artifact emission rather than weakening parity.
- Core ML model-directory enumeration must exclude the external receipt file
  and use sorted relative paths; exact helper names are implementation-local.
