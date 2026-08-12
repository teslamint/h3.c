---
schema: plan/v1
title: ANE Eligibility and Qualification Diagnostics
type: feat
status: done
completed_by: 47bd2c5c3d060a9f925b86347204b9860ac86a8d
date: 2026-08-12
execution: code
origin: docs/specs/2026-08-12-ane-eligibility-fix-design.md
deepened: true
body_seal: 185ccaec018f13919b22c1e3e96656bf527b83b7db68ae47a4bab0a6eb0a7f19
---

# ANE Eligibility and Qualification Diagnostics Plan

## Goal

Make every ANE qualification failure actionable, replace the production
compute-plan collector that rejects the 441-operation fixed candidate, and emit a
mathematically equivalent five-dimensional FL2VA block whose nonconstant
operations are all Neural Engine eligible on the target machine. Preserve Metal
as the default and fail-closed path, and publish authority only after real parity.

## Architecture notes

- Keep `h3.h` unchanged. The private ANE bridge owns an immutable first-failure
  record; qualifier and tests copy it through `h3_ane_diagnostic_snapshot` rather
  than parsing stderr or replacing it with `ANE backend is unavailable`.
  Qualifier-owned boundaries record into a tool-local diagnostic with the same
  `h3_ane_diagnostic_record_first` helper, then merge a handle snapshot only while
  the tool-local stage is `NONE`.
- Add closed `h3_ane_stage` and `h3_ane_code` enums matching the approved spec's
  taxonomy. Existing `h3_ane_reason` remains the compact fallback/statistics
  category; one mapping function supplies a reason for every stage/code pair.
- The first failed boundary wins in this fixed order: setup/caller contract,
  artifact hashing, receipt, Core ML load, creator/I/O contract, compute plan,
  eligibility, input, prediction, output, parity, publication. Authorized
  qualification intentionally skips receipt authority, so creator metadata is
  observable there.
- The bridge stores no private paths or arbitrary `NSError` strings in structured
  results. Diagnostic messages come from stable literals. Operation names are
  copied into a 96-byte bounded buffer; unknown device classes serialize as null
  and fail eligibility for nonconstant operations.
- Replace `H3_ANE_MAX_OPERATIONS = 256` and the stack array with a production
  two-pass traversal. Pass one recursively counts operations and rejects zero,
  overflow, nesting over 64, or count over 4096. Pass two allocates exactly the
  count, fills it, and rejects count/fill drift. Constant operations with nil
  device usage are retained for evidence but do not fail eligibility.
- Change private real/test backend callbacks to return success/failure while
  writing `h3_ane_diagnostic *`: `load(opaque, diagnostic)`,
  `plan(opaque, operations, count, diagnostic)`, and
  `predict(opaque, input, input_count, output, output_count, diagnostic)`. Plan
  count/fill mismatch fails, and fake backends inject exact codes without parsing
  messages.
- Add a recursive test adapter. `h3_ane_test_plan_node` owns one operation usage
  plus caller-owned children/count; `h3_ane_test_collect_plan` invokes the same
  generic bounded count/fill walker as the Objective-C adapter. This seam, not a
  flat fake buffer, proves the 64/65 nesting boundary.
- Preserve `h3_ane_inventory_summary` on each handle after create. It records
  total, constant, nonconstant, Neural Engine-supported, CPU-only, GPU-only,
  unknown-nonconstant, and constant-nil-usage counts. Native tools snapshot it;
  they do not duplicate traversal or classification.
- Preserve the public F32 NDHWC `[1,1,256,256,128]` model boundary. Internally
  squeeze the singleton depth, normalize each consecutive four-channel group
  with native `layer_norm` over H/W/C, concatenate all 32 groups, and apply the
  released affine vectors in original channel order.
- For the approved fixed depth-one boundary with two-front temporal zero padding,
  only OIDHW temporal plane index 2 can contribute. Convert that OIHW plane to a
  reflected-pad 2D convolution. Deterministic tests make temporal planes 0 and 1
  nonzero so an erroneous plane selection cannot pass accidentally.
- Keep conversion tooling pinned to Python 3.12, coremltools 9.0, NumPy 2.3.2,
  and safetensors 0.6.2. The C runtime gains no Python dependency.
- Treat `MLComputePlan` usage only as anticipated placement. Installed SDK
  `MLComputePlan.h` and Apple's `deviceUsage(for:)` documentation use that term;
  only the later Instruments gate may claim observed Neural Engine execution.

## Assumption Recheck

| Approved claim | Fresh command | Observed at | Fresh result | Outcome |
|---|---|---|---|---|
| The retained U4 artifact is stale but Core ML-loadable, with prefixed creator keys that current runtime rejects. | `rg -n 'h3_ane_contract_version|h3_ane_variant|"version"|"variant"' /private/tmp/ane-u4-compiled/ane-u4-real.mlmodelc/metadata.json` plus the production trace retained during diagnosis | `2026-08-12T01:41:36Z` | Artifact still contains `h3_ane_contract_version` and `h3_ane_variant`; production trace previously reached `reason=contract`, not a Core ML load error. | match |
| The current decomposed fixed block contains CPU-only nonconstant operations. | Compile `docs/evidence/ane-eligibility/design-plan-probe.m` and run it against `/private/tmp/u4-fixed.mlmodelc`. | `2026-08-12T01:41:36Z` | 35 nonconstant operations; 19 support Neural Engine and 16 are CPU-only. | match |
| The exact five-dimensional real-weight candidate has no unknown or CPU-only nonconstant operation before the production cap. | Run the four commands recorded in `docs/evidence/ane-eligibility/2026-08-12-design-probe.json` using the committed probe sources. | `2026-08-12T01:34:58Z` | Exact F32 `[1,1,256,256,128]` artifact reports 441 total, 149 nonconstant, 149 Neural Engine-supported, and 0 unknown nonconstant operations; source hashes match v2 evidence. | match |
| The current production collector rejects that candidate before eligibility because it is capped at 256 operations. | `rg -n 'H3_ANE_MAX_OPERATIONS|operations\[H3_ANE_MAX_OPERATIONS\]' h3_ane.m` and production qualification against `/private/tmp/ane-evidence-5d.mlmodelc`. | `2026-08-12T01:41:36Z` | Source cap remains 256; production result exits 1 at compute-plan unavailable and writes no receipt. | match |
| Compute-plan device usage is anticipated execution-device evidence, not observed execution. | `rg -n -C 3 'computeDeviceUsageForMLProgramOperation|anticipated' "$(xcrun --show-sdk-path)/System/Library/Frameworks/CoreML.framework/Headers/MLComputePlan.h"` | `2026-08-12T01:41:36Z` | Installed SDK says the method returns anticipated compute devices or nil when undetermined. | match |

No contradiction or unavailable approved assumption remains. The spec needs no
deviation addendum before implementation.

## File structure

### Diagnostic contract and qualifier output

- Modify `h3_ane.h`: add closed stage/code enums, complete bounded diagnostic
  context, inventory summary, structured testing callbacks, and recursive
  test-plan nodes without changing `h3.h`.
- Modify `h3_ane_internal.h`: expose `h3_ane_diagnostic_snapshot` and the
  authorized-qualification contract used by the video encoder tool path; expose
  `h3_ane_diagnostic_record_first`, `h3_ane_diagnostic_merge_first`, and
  `h3_ane_inventory_snapshot` for native tools.
- Modify `h3_ane.m`: preserve the first failure, map every bridge boundary to one
  stable stage/code, retain bounded operation/device context, and keep fallback
  statistics separate from diagnostics.
- Modify `h3_video_encoder.c`: return the copied diagnostic from
  `h3_video_encoder_block0_qualification` even when prediction observes a handle
  already marked unavailable.
- Modify `h3_video_encoder.h`: extend only the private qualification signature;
  generation and `h3_video_latent` interfaces remain compatible.
- Modify `tests/qualify_ane.c`: serialize the closed diagnostic fields and the
  stderr-only result-publication failure contract.
- Modify `tests/test_ane.c` and `tests/test_ane_tools.py`: table-drive every
  stage/code, first-failure preservation, safe JSON context, and receipt absence.

### Bounded compute-plan inventory

- Modify `h3_ane.m`: implement count/fill traversal with the approved 4096
  operation and 64 nesting limits, checked allocation, and constant-nil handling.
- Modify `h3_ane.h`: define the structured plan callback and recursive
  `h3_ane_test_plan_node`/`h3_ane_test_collect_plan` seam.
- Modify `h3_ane_internal.h`: expose the production inventory snapshot used by
  the thin U4 probe.
- Modify `tests/test_ane.c`: synthesize eligible 441-operation, excessive
  4097-operation, deep-65, empty, count/fill-drift, unknown, and CPU-only plans.

### Fixed graph conversion and mathematical tests

- Modify `scripts/convert_ane_visual_block.py`: replace manual reduction-based
  group norm and full 3D convolution with the approved 5D-boundary candidate.
- Modify `tests/test_ane_tools.py`: prove grouping/affine/channel order, spatial
  reflect edges and corners, temporal plane selection, residual, canonical
  metadata, and deterministic graph/reference parity.

### Compiler/runtime integration and evidence

- Create `scripts/run_ane_integration.py`: one pinned, noninteractive coordinator
  with `synthetic` and `real` modes. Synthetic mode creates a deterministic
  complete eight-tensor exact-shape fixture and is always runnable on supported
  macOS/Xcode with pinned packages. Real mode requires an explicit released
  weight directory. Both invoke `coremlcompiler` and the production
  loader/collector. Synthetic mode stops after metadata/schema/inventory and
  never writes a qualification receipt; real mode additionally invokes the full
  production qualifier, structured result/receipt validation, and parity.
- Create `tests/ane_integration_probe.m`: production-reader probe linked from the
  same `h3_ane.m` object rather than duplicating metadata or plan logic.
- Modify `Makefile`: add `h3_ane_integration_probe`, always-runnable
  `h3_ane_integration_test`, and conditional `h3_ane_real_qualification_test`.
  Define `ANE_UV_CACHE ?= /private/tmp/uv-cache`,
  `ANE_INTEGRATION_WORK ?= /private/tmp/h3-ane-integration`, and
  `ANE_INTEGRATION_OUTPUT ?= .release-loop/evidence/ane-integration.json`.
  The real target requires `H3_ANE_WEIGHT_DIR`; absence exits 2 with a literal
  prerequisite error. Neither target is a dependency of `all` or normal `test`.
- Modify `tests/test_ane_tools.py`: cover coordinator validation, stale metadata,
  rerun, failure, and cancellation using disposable directories.
- Modify `docs/evidence/ane-eligibility/2026-08-12-design-probe.json` only if
  compiler inventory legitimately drifts during implementation; any change must
  refresh all v2 hashes and be independently reviewed before qualification.

### Operator documentation and tracker

- Modify `docs/ane-acceleration.md`: document structured failure fields, exact
  integration target, eligible graph boundary, and evidence terminology.
- Modify `README.md`: keep the high-level default-off workflow synchronized.
- Modify `ROADMAP.md`: mark gate 1 and gate 7 passed only from fresh exact-command
  evidence; mark gate 2 passed only from a real matching receipt. Leave gates 3–6
  blocked because this loop does not produce observed placement or performance.

## Scenario coverage map

| Scenario | Ordered unit chain | Walking evidence |
|---|---|---|
| S1 diagnose qualification | U1 → U4 | U4 stale-metadata integration run asserts `contract/metadata_missing`, null operation context, no receipt, and no generic-only failure. Covers S1. |
| S2 reject stale package at compiler/runtime boundary | U1 → U2 → U4 | U4 compiles stale and canonical packages, loads both through the production reader, rejects stale creator keys, and advances canonical input through production plan traversal. Covers S2. |
| S3 build eligible fixed candidate | U2 → U3 → U4 | U4 exact 5D real-weight run asserts 441 total, 149 nonconstant, 149 Neural Engine-supported, zero unknown/CPU-only, and no inventory truncation. Covers S3. |
| S4 qualify parity and authority | U1 → U2 → U3 → U4 | U4 production qualification runs unchanged Metal and Core ML outputs, checks `max_abs < 0.002` and `relative_l2 < 0.02`, and validates one digest-bound receipt. Covers S4. |
| S5 keep claims layered | U1 → U4 → U5 | U4 labels plan usage anticipated/eligible; U5 command and terminology audit reserves observed placement for Instruments. Covers S5. |

## Implementation Units

## U1: Preserve structured first-failure diagnostics
Execution note: test-first
Files:
  Create: none
  Modify: h3_ane.h, h3_ane_internal.h, h3_ane.m, h3_video_encoder.h, h3_video_encoder.c, tests/qualify_ane.c, tests/test_ane.c, tests/test_ane_tools.py
  Test: tests/test_ane.c, tests/test_ane_tools.py
Interfaces:
  Consumes: existing `h3_ane_reason`, create/load/predict boundaries, `h3_video_encoder_block0_qualification`, qualifier result writer
  Produces: `h3_ane_stage` with `NONE, SETUP, ARTIFACT, CONTRACT, RECEIPT, LOAD, COMPUTE_PLAN, ELIGIBILITY, INPUT, PREDICTION, OUTPUT, PARITY, PUBLICATION`; `h3_ane_code` with `NONE, DISABLED, OS_UNSUPPORTED, ALLOCATION_FAILED, COMPILED_MODEL_UNREADABLE, COMPILED_MODEL_DIGEST_FAILED, SOURCE_WEIGHTS_UNREADABLE, SOURCE_TENSOR_DIGEST_FAILED, METADATA_MISSING, METADATA_MISMATCH, FINGERPRINT_MISMATCH, SHAPE_MISMATCH, DTYPE_MISMATCH, RECEIPT_MISSING, RECEIPT_MALFORMED, RECEIPT_DIGEST_MISMATCH, RECEIPT_INVALID, MODEL_LOAD_FAILED, MODEL_LOAD_EXCEPTION, PLAN_TIMEOUT, PLAN_LOAD_FAILED, PROGRAM_MISSING, MAIN_MISSING, OPERATION_INVENTORY_EMPTY, OPERATION_INVENTORY_LIMIT_EXCEEDED, OPERATION_NESTING_LIMIT_EXCEEDED, OPERATION_INVENTORY_CHANGED, OPERATION_USAGE_UNKNOWN, OPERATION_NOT_NEURAL_ENGINE_SUPPORTED, DEVICE_UNKNOWN, INPUT_SHAPE_MISMATCH, INPUT_DTYPE_MISMATCH, INPUT_COPY_FAILED, PREDICTION_FAILED, PREDICTION_EXCEPTION, OUTPUT_SHAPE_MISMATCH, OUTPUT_DTYPE_MISMATCH, OUTPUT_COPY_FAILED, OUTPUT_NONFINITE, PARITY_METRICS_NONFINITE, PARITY_BOUNDS_FAILED, RESULT_WRITE_FAILED, RECEIPT_WRITE_FAILED`; `h3_ane_artifact_role { NONE, COMPILED_MODEL, SOURCE_WEIGHTS }`; `h3_ane_contract_field { NONE, VERSION, VARIANT, BLOCK_LEVEL, BLOCK_INDEX, WEIGHT_PREFIX, BOUNDARY_DTYPE, SHAPE, SOURCE_SHA256 }`; `h3_ane_diagnostic { h3_ane_stage stage; h3_ane_code code; h3_ane_reason reason; char message[160]; char operation[96]; h3_ane_artifact_role artifact_role; h3_ane_contract_field contract_field; char digest[65]; uint32_t supported_devices; uint32_t preferred_device; uint64_t observed_count; uint64_t limit; double max_abs; double relative_l2; unsigned has_operation:1; unsigned has_artifact_role:1; unsigned has_contract_field:1; unsigned has_digest:1; unsigned has_supported_devices:1; unsigned has_preferred_device:1; unsigned has_count:1; unsigned has_metrics:1; }`; `void h3_ane_diagnostic_record_first(h3_ane_diagnostic *, h3_ane_stage, h3_ane_code, h3_ane_reason, const char *message)`; `void h3_ane_diagnostic_merge_first(h3_ane_diagnostic *, const h3_ane_diagnostic *)`; `void h3_ane_diagnostic_snapshot(h3_ane *, h3_ane_diagnostic *)`; qualification returns the copied diagnostic through an output pointer
  Produces additionally: testing callback signatures `int (*load)(void *, h3_ane_diagnostic *)`; `int (*plan)(void *, h3_ane_operation_usage *, size_t *, h3_ane_diagnostic *)`; `int (*predict)(void *, const float *, size_t, float *, size_t, h3_ane_diagnostic *)`; each returns 1 only on success and otherwise must set one exact diagnostic code
Test scenarios:
  happy: a successful qualifier result serializes every failure field as null and leaves `H3_ANE_REASON_NONE`
  edge: constant nil usage carries no failure; absent operation/device/count/metric contexts serialize as null; bounded strings are terminated
  error: table rows exercise setup, artifact, contract, receipt, load, compute_plan, eligibility, input, prediction, output, parity, and publication codes; the first diagnostic is immutable when fallback accounting or later prediction occurs
  integration: authorized stale-metadata qualification preserves `contract/metadata_missing` through video encoder and qualifier JSON and writes no receipt, Covers S1
Steps:
  1. Add failing native and Python assertions for the full stage/code table, null context, first-failure immutability, successful-null fields, result-write stderr exit 2, receipt-write result rewrite, and receipt absence.
  2. Run `make h3_ane_tests && ./h3_ane_tests && python3 -m unittest discover -s tests -p 'test_ane_tools.py'`; confirm failures are the missing diagnostic API/JSON fields, not build setup.
  3. Add the closed enums/struct and one `record_first_diagnostic` helper in `h3_ane.m`; map existing reason sites without changing Metal fallback decisions or counters.
  4. Extend the private qualification signature and result writer; use stable literal messages, redact paths/`NSError`, and preserve stderr-only behavior when the result cannot be published.
  5. Rerun focused tests, strict compiler warnings, and `git diff --check`.
  6. Commit: `feat(ane): Preserve qualification failure diagnostics`
Acceptance: `make h3_ane_tool_tests && make h3_ane_tests && ./h3_ane_tests && python3 -m unittest discover -s tests -p 'test_ane_tools.py'` passes; every failed fixture has one stable stage/code and no passing receipt.

## U2: Replace the fixed compute-plan operation cap
Execution note: test-first
Files:
  Create: none
  Modify: h3_ane.h, h3_ane_internal.h, h3_ane.m, tests/test_ane.c
  Test: tests/test_ane.c
Interfaces:
  Consumes: `MLComputePlan`, recursive `MLModelStructureProgramBlock` trees, `h3_ane_operation_usage`, U1 diagnostic; structured `int (*plan)(void *, h3_ane_operation_usage *, size_t *, h3_ane_diagnostic *)` where null operations requests count and nonnull operations receives exact capacity
  Produces: constants `H3_ANE_MAX_OPERATIONS = 4096` and `H3_ANE_MAX_OPERATION_DEPTH = 64`; `h3_ane_inventory_summary { uint64_t total; uint64_t constant; uint64_t nonconstant; uint64_t neural_engine_supported; uint64_t cpu_only; uint64_t gpu_only; uint64_t unknown_nonconstant; uint64_t constant_nil_usage; }`; `void h3_ane_inventory_snapshot(h3_ane *, h3_ane_inventory_summary *)`; `h3_ane_test_plan_node { h3_ane_operation_usage usage; const h3_ane_test_plan_node *children; size_t child_count; }`; `int h3_ane_test_collect_plan(const h3_ane_test_plan_node *, size_t, h3_ane_operation_usage **, size_t *, h3_ane_inventory_summary *, h3_ane_diagnostic *)`; exact-count heap inventory and count/fill mismatch mapped to `COMPUTE_PLAN/OPERATION_INVENTORY_CHANGED`
Test scenarios:
  happy: a synthetic 441-operation tree with 149 eligible nonconstant operations passes count/fill and eligibility with no truncation
  edge: 4096 total operations and depth 64 pass; constant operations with nil usage are counted but accepted; allocation size is overflow checked
  error: zero operations, 4097 operations, depth 65, count/fill drift, unknown nonconstant usage/device, CPU-only, and GPU-only operations fail with exact first stage/code/context
  integration: the real 441-operation five-dimensional design artifact passes the production collector and reaches prediction rather than `compute_plan`, Covers S2, Covers S3
Steps:
  1. Add failing fake-plan tests for 441/4096/4097 counts, 64/65 depth, count/fill drift, constant nil usage, unknown nonconstant usage, and unsupported device masks.
  2. Run `make h3_ane_tests && ./h3_ane_tests`; confirm the 441 fixture fails because the existing 256-entry stack collector rejects it.
  3. Implement shared recursive count/fill helpers with checked depth/count/allocation, then adapt the real Core ML and testing backends without duplicating acceptance rules.
  4. Free the inventory on every return path after reducing it into stats/diagnostic state; preserve the five-second real plan timeout.
  5. Rerun focused tests, AddressSanitizer on the focused binary if supported, strict warnings, and `git diff --check`.
  6. Commit: `fix(ane): Support bounded large compute plans`
Acceptance: `make h3_ane_tests && ./h3_ane_tests` passes the 441 fixture and all bounds; `H3_ANE_TRACE=1` production load of the design artifact emits operation rows instead of `Core ML compute plan is unavailable`.

## U3: Emit the eligible five-dimensional fixed graph
Execution note: test-first
Files:
  Create: none
  Modify: scripts/convert_ane_visual_block.py, tests/test_ane_tools.py
  Test: tests/test_ane_tools.py
Interfaces:
  Consumes: existing sorted FL2VA tensor selection and source digest; OIDHW `(128,128,3,3,3)` weights; F32 NDHWC `(1,1,256,256,128)` boundary
  Produces: canonical-metadata ML Program that squeezes/restores singleton depth, applies 32 four-channel native layer norms with epsilon `1e-6`, released affine vectors, reflected spatial padding, OIHW temporal plane index 2 as two 2D convolutions, SiLU, residual, and F32 output
Test scenarios:
  happy: deterministic nontrivial real-shape fixture matches NumPy reference with `max_abs < 0.002` and preserves canonical metadata/source digest
  edge: every group boundary and channel order, affine scale/bias, reflect edges/corners, residual, and F32 input/output are pinned
  error: nonzero sentinel weights in temporal planes 0 and 1 cannot affect depth-one output while plane 2 does; wrong plane, group axis, epsilon, affine broadcast, or spatial pad fails the reference test
  integration: a pinned package compiles to the exact five-dimensional schema and U2 production collector reports 441 total, 149 nonconstant, 149 Neural Engine-supported, zero CPU-only/unknown, Covers S3
Steps:
  1. Add failing small-tensor algebra tests and a compiled-schema test for temporal-plane selection, group normalization, padding, residual, F32 boundary, and canonical metadata.
  2. Run `python3 -m unittest discover -s tests -p 'test_ane_tools.py'`; confirm the current reduction/Conv3D graph violates the new inventory/equivalence assertions.
  3. Replace only the graph construction helpers; reuse tensor loading, digest, atomic package publication, and compiler invocation.
  4. Run the deterministic Python reference test and pinned `coremlcompiler`; inspect compiled metadata and production plan summary.
  5. Commit: `fix(ane): Emit Neural Engine eligible visual block`
Acceptance: Python tests pass; compiled input/output are exact F32 5D; sanitized summary is `441/149/149/0`; no compiled artifact is committed.

## U4: Add the compiler-to-receipt integration gate
Execution note: test-first
Files:
  Create: scripts/run_ane_integration.py, tests/ane_integration_probe.m
  Modify: Makefile, tests/test_ane_tools.py, tests/qualify_ane.c
  Test: tests/test_ane_tools.py, tests/ane_integration_probe.m
Interfaces:
  Consumes: pinned converter environment, `xcrun coremlcompiler`, production `h3_ane` reader/collector, real FL2VA weight directory, `h3_ane_qualification`
  Produces: always-runnable `make h3_ane_integration_test` using generated deterministic exact-shape block tensors for compile/load/inventory only; explicit `H3_ANE_WEIGHT_DIR=/absolute/released/source make h3_ane_real_qualification_test` for full encoder loading, Metal/Core ML parity, and receipt; `h3_ane_integration_probe MODEL.mlmodelc --source-sha256 HEX --output SUMMARY.json` calls production diagnostic/inventory snapshots; sanitized `h3-ane-integration/v1` summary uses null parity/receipt in synthetic mode and real metrics/receipt in real mode
Test scenarios:
  happy: canonical synthetic package compiles and passes production metadata/schema/inventory with null parity/receipt; explicit real mode additionally passes Metal/Core ML parity and publishes one real receipt
  edge: rerun replaces only temporary/unqualified outputs, stable inventory is validated, constant nil usage is reported separately, and headless invocation needs no prompts
  error: stale prefixed metadata, compiler failure, 4097 operations, unknown/CPU-only nonconstant use, parity perturbation, receipt write failure, and result write failure produce exact diagnostics and no authority
  integration: the synthetic target always generates, compiles, production-loads, inventories, and emits bounded evidence with no receipt; the explicit real target alone qualifies and walks S4 when `H3_ANE_WEIGHT_DIR` is supplied, Covers S1, Covers S2, Covers S3, Covers S4
Steps:
  1. Add failing coordinator tests using disposable directories and test injection seams for stale metadata, compiler failure, parity failure, publication failure, rerun, and SIGTERM cleanup.
  2. Add `tests/ane_integration_probe.m` as a thin CLI over production diagnostic/plan APIs; do not copy creator-key or eligibility logic into the probe.
  3. Add `scripts/run_ane_integration.py MODE` with explicit `--repo`, `--work-dir`, and `--output`; synthetic mode generates all eight block tensors and stops after the production inventory probe with parity/receipt null, while real mode requires `--weights` and invokes `h3_ane_qualification`. Make every child command an argv vector, cap captured output, and atomically publish only the sanitized summary.
  4. Add Make variables `ANE_UV_CACHE ?= /private/tmp/uv-cache`, `ANE_INTEGRATION_WORK ?= /private/tmp/h3-ane-integration`, and `ANE_INTEGRATION_OUTPUT ?= .release-loop/evidence/ane-integration.json`; use the pinned uv command. The real target exits 2 with `H3_ANE_WEIGHT_DIR is required for h3_ane_real_qualification_test` before Python when absent.
  5. Run `make h3_ane_integration_test`; confirm stale metadata rejection, `441/149/149/0`, null parity fields, and no receipt without released assets. Run `H3_ANE_WEIGHT_DIR="$PWD/MiniMax-H3/FL2VA/video_vae/source" make h3_ane_real_qualification_test`; confirm real parity and one matching receipt.
  6. Rerun focused and full actual-Metal suites, verify cancellation leaves no final result/receipt/temp, and commit: `test(ane): Add compiler-to-receipt integration gate`
Acceptance: `make h3_ane_integration_test` exits zero without released assets, reports `441/149/149/0`, null parity/receipt, and creates no sidecar; `H3_ANE_WEIGHT_DIR="$PWD/MiniMax-H3/FL2VA/video_vae/source" make h3_ane_real_qualification_test` exits zero in this checkout and produces a real summary/receipt; focused and full tests pass.

## U5: Align operator workflow and evidence tracker
Execution note: skip-test-first
Files:
  Create: none
  Modify: docs/ane-acceleration.md, README.md, ROADMAP.md
  Test: documentation command/terminology audit
Interfaces:
  Consumes: U1 structured result schema, U4 exact Make target/summary, local qualification receipt, existing Instruments/performance gates
  Produces: operator commands for diagnostics and integration; precise eligible/preferred/observed terminology; ROADMAP gate status backed by exact command results
Test scenarios:
  happy: an operator follows docs from conversion through integration and qualification with the exact 5D artifact
  edge: absent pinned packages is dependency unavailable; absent real weights affects only the explicit real target with its exit-2 prerequisite message, while synthetic integration remains runnable; neither is mislabeled ANE failure
  error: docs never call eligibility, preferred device, parity, or receipt “observed ANE”; gate 2 cannot pass without matching real receipt
  integration: run documented help/build/integration commands and terminology scans; retained summary plus docs complete S5, Covers S5
Steps:
  1. Update result-field and integration-target documentation, including stage/code examples and the result-write stderr exception.
  2. Document the 5D graph restriction, 4096/64 safety limits, exact pinned environment, local-artifact policy, and the distinction between eligibility, qualification, and observed placement.
  3. Run every documented `--help`/Make command, scan README/docs/evidence for stale generic-only or placement-overclaim language, and run `git diff --check`.
  4. Mark ROADMAP gate 1 and gate 7 passed only if their exact commands pass; mark gate 2 passed only if U4 produced a matching receipt; leave gates 3–6 blocked.
  5. Commit: `docs(ane): Document eligibility qualification workflow`
Acceptance: commands match implemented flags/targets; ROADMAP statuses cite current evidence; no public `h3.h` change or observed-placement claim exists.

## Mutation/failure-state matrix

| Transition | Pre-state | Action | Expected post-state | Success | Forced failure | Rerun | Rollback or compensation | Headless | Cancellation or abort | Unit / evidence owner |
|---|---|---|---|---|---|---|---|---|---|---|
| Publish converted `.mlpackage` | Immutable source weights; final package absent or unqualified | Build under a temporary sibling and atomically rename | Complete canonical package; no receipt | Canonical metadata/source digest readable after rename | U4 supplies an isolated wrong-shape tensor fixture; converter exits nonzero and final package stays absent | New temporary sibling replaces only after full save; it never appends | Remove unqualified package; immutable weights are compensation source | U4 coordinator passes all paths/versions as flags and never prompts | SIGTERM handler removes temporary sibling; runtime cannot authorize a package | U3/U4 / `.release-loop/evidence/U4/conversion.json` |
| Publish compiled `.mlmodelc` | Complete package; compiled destination absent or unqualified | Run `coremlcompiler` into temporary output and atomically rename the single model | Production-loadable compiled directory; no receipt | Production reader validates canonical metadata and exact F32 5D schema | U4 invokes a fake compiler for unit coverage and a malformed isolated package for native coverage; no final directory is published | Existing unqualified destination is replaced only after a fresh compile | Remove unqualified compiled directory; package remains reproducible | Compiler/coordinator are argv-driven and noninteractive | Coordinator terminates child, removes temporary compile directory, and leaves receipt absent | U4 / `.release-loop/evidence/U4/compile.json` |
| Publish integration summary | No final summary or a prior complete summary | Run all stages into a work directory and atomically rename sanitized JSON last | One bounded complete `h3-ane-integration/v1` summary | Schema, hashes, inventory, diagnostics, metrics, and exit statuses validate | Inject child failure after compile; final summary is a complete failed-status record and raw logs remain local/capped | Rerun creates a new temporary summary and replaces final only after fsync/rename | Delete summary; it grants no runtime authority | Synthetic mode is fully defined by `--repo --work-dir --output`; real mode additionally requires `--weights`; neither prompts | SIGTERM removes temporary summary and children; previous complete summary remains unchanged | U4 / `.release-loop/evidence/U4/integration.json` |
| Invalidate prior receipt | Existing passing receipt may authorize current digest | Atomically rename to `.invalid` before any new measurement | No loadable authority during qualification | Old receipt is non-loadable before Core ML comparison begins | Inject rename failure in disposable directory; qualifier exits 2 before prediction and leaves original receipt state explicit | Every rerun performs the same invalidation before work | Operator may restore only by rerunning successful qualification; `.invalid` is audit evidence, not authority | Qualifier uses flags only and emits stable exit/JSON | SIGTERM after invalidation leaves `.invalid`; no valid receipt exists | U1/U4 / `.release-loop/evidence/U4/receipt-invalidation.json` |
| Publish initial qualification RESULT | Receipt is invalidated; deterministic measurement has passed or failed; result destination absent or prior-complete | Write complete failed/passed JSON to a temporary sibling, fsync, and rename before any receipt publication | One atomic RESULT recording the first diagnostic and metrics; still no new receipt | Reader observes complete schema and matching digests/metrics | Inject result-open/fsync/rename failure in disposable directory; tool emits `publication/result_write_failed` on stderr, exits 2, and writes no receipt | Rerun replaces RESULT only through a fresh complete temporary file | Delete RESULT; it grants no runtime authority and receipt remains absent | Flags define all paths; stderr is the fallback evidence when RESULT cannot exist | SIGTERM removes temporary RESULT and leaves no final new RESULT/receipt | U1/U4 / `.release-loop/evidence/U4/result-publication.json` |
| Publish passing receipt | Result says passed, compiled/source digests known, old authority invalidated | Write temporary sidecar, fsync, and rename last | Exactly one receipt bound to current model/source and metrics | Runtime validation and reread match result fields | Inject receipt writer failure; result rewrites to `publication/receipt_write_failed`, receipt is absent | Rerun invalidates any current receipt and requires parity again | Delete/rename receipt to disable non-shadow use; Metal remains compensation | No prompts; exit zero only after reread validation | SIGTERM removes receipt temp; no final receipt is created | U1/U4 / `.release-loop/evidence/U4/receipt-publication.json` |
| Rewrite RESULT after receipt publication failure | Initial RESULT says passed; receipt publication failed; receipt absent | Atomically replace RESULT with failed `publication/receipt_write_failed` document | RESULT and receipt authority agree that qualification failed | Replacement succeeds and reread has failed status/code | Inject rewrite failure after receipt failure; stderr reports both publication failures, receipt remains absent, exit 2 | Rerun starts by invalidating any authority and recomputes all stages | Manual recovery is rerun qualification; no receipt means Metal compensation remains authoritative | No prompts; both failures use stable stderr literals | SIGTERM removes rewrite temp; a stale passed RESULT may remain but cannot authorize without receipt | U1/U4 / `.release-loop/evidence/U4/result-rewrite.json` |
| Adopt Core ML request output | Valid matching receipt and immutable GPU input | Predict into separate host buffer, validate, allocate replacement GPU tensor, then adopt | Request returns Core ML result only after all online checks | Stats show one prediction, no fallback, finite exact-count output | Existing fake seams inject input/prediction/output/allocation failures; original pointer runs Metal | Every request starts from immutable input and revalidates online artifact/receipt state | Pointer-identical Metal path is compensation; no durable model mutation exists | Environment/CLI controls selection without prompts | Process abort discards request-local buffers; model/receipt stay unchanged and next run revalidates | U1/U2/U4 / `.release-loop/evidence/U4/runtime-adoption.json` |

## Carry-forward trigger audit

All seven ROADMAP gates are event-based because each fires only when its named
future evidence event occurs; none names a file edit or an already-latched drift.
No trigger has fired at planning time. Feature relevance is separate from firing:
gate 1 is folded into U1/U5, gate 2 into U4/U5, and gate 7 into U4/U5 because the
approved feature explicitly pursues those future events. Gates 3–6 remain
deferred. Implementation updates status only after each event's exact evidence
exists.

Audited `ROADMAP.md` at `c07146f`: 7 open rows, 0 fired, 0 unobservable.

## Deferred to Follow-Up Work

- ROADMAP gate 3 observed Neural Engine placement remains blocked until a
  sanitized Instruments trace overlaps the prediction interval.
- ROADMAP gates 4–6 latency, RSS, and energy remain blocked until gate 3 and their
  independent measurements pass; qualification or eligibility cannot substitute.
- Graph operation-count optimization is deferred until availability/parity and
  observed placement exist; this loop does not trade correctness for fewer ops.
- Broader visual blocks, deeper temporal boundaries, DiT, audio, text, decoder,
  dynamic shapes, and default-on Core ML remain separate designs.
- Bundling model packages or compiled artifacts remains out of scope because
  weights, licenses, distribution, and repository size require separate approval.

## Open unknowns

### Planning-time

None. Failure precedence, safety bounds, graph semantics, evidence terms, unit
boundaries, and success commands are fixed by the approved spec and fresh probes.

### Implementation-time

- Exact internal helper names for count/fill traversal and diagnostic recording
  are implementation-local; their observable enums, limits, and precedence are
  fixed above.
- Core ML compiler inventory may drift from 441/149 on a different installed
  compiler or OS. U4 must fail the pinned evidence tuple and require refreshed
  reviewed evidence rather than silently accepting drift.
- Actual Metal/Core ML parity is intentionally resolved only by U4's real run.
  If it fails, retain the structured result and stop gate 2; do not loosen bounds
  or claim backend availability.
