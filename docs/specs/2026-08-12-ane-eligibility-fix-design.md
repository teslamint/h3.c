---
title: ANE Eligibility and Qualification Diagnostics
status: approved
date: 2026-08-12
schema: spec/v1
---

# ANE Eligibility and Qualification Diagnostics Design

_Created 2026-08-12._

## Overview

Repair the fixed FL2VA visual-encoder experiment so an operator can distinguish
artifact, contract, compute-plan, placement-preflight, and prediction failures,
then replace the CPU-partitioned Core ML graph with a mathematically equivalent
candidate whose nonconstant operations are all Neural Engine eligible on the
target Apple Silicon machine. The default Metal path, qualification receipt
authority, and fail-closed fallback contract remain unchanged.

This project restores **backend availability evidence**. It does not claim
observed Neural Engine execution, latency, memory, energy, or product-level
acceleration unless the existing later evidence gates are separately satisfied.

## User Scenarios

### S1: Diagnose a failed qualification without trace archaeology

An operator runs the existing qualification command against a stale or invalid
compiled model. The failed JSON result identifies the first failing stage with
a stable reason code and safe structured context instead of reporting only
`ANE backend is unavailable`. No passing receipt exists after failure.

```sh
make h3_ane_qualification
H3_ANE_TRACE=1 ./h3_ane_qualification \
  --model MiniMax-H3/FL2VA/video_vae/source \
  --coreml-model "$H3_ANE_MODEL" \
  --output .release-loop/evidence/ane-qualification.json
```

### S2: Reject a stale package at the real compiler/runtime boundary

An operator runs one pinned integration command that creates a package, compiles
it, loads the compiled model through the production metadata consumer, traverses
its compute plan, and attempts qualification. Producer-only and consumer-only
unit tests cannot substitute for this boundary test. A canonical-key mismatch is
reported as `contract`, not as prediction failure.

### S3: Build an eligible fixed-block candidate without weakening policy

The converter emits a fixed-shape model that preserves the released FL2VA block's
normalization, padding, convolution, residual, dtype-boundary, and source-weight
identity. Every nonconstant ML Program operation must advertise Neural Engine
support. A CPU-only or unknown operation rejects the candidate before prediction;
mixed CPU/Neural Engine execution is not accepted as a workaround.

### S4: Qualify actual prediction parity before granting authority

On the target machine, the qualifier executes both the unchanged Metal oracle and
the eligible Core ML candidate using the deterministic input. It publishes a
receipt only when the existing maximum-absolute and relative-L2 bounds pass and
the compiled-model and source-tensor digests match.

### S5: Keep operational claims evidence-layered

Documentation and result artifacts label compute-plan device support as
`eligibility`, not observed placement. The operator may proceed to Instruments,
latency, RSS, and energy gates only after qualification, and only Instruments
activity overlapping prediction can support an observed-ANE claim.

## Scope

### In

- Stage-specific, machine-readable qualification diagnostics.
- Preservation of the first unavailable reason through qualification output.
- Safe operation-level context for compute-plan rejection.
- A pinned package-to-compile-to-production-runtime integration gate.
- Regeneration of canonical creator metadata; stale prefixed metadata remains
  rejected rather than silently migrated.
- A fixed-shape FL2VA level-0/block-0 graph representation that preserves the
  public `[1,1,256,256,128]` F32 NDHWC boundary.
- Mathematical reduction of depth-one temporally front-padded convolution to the
  weight plane that can affect the sole output depth.
- Group normalization represented without CPU-only reduction decomposition.
- Actual target-machine eligibility, parity, receipt, and Metal-fallback tests.
- Operator documentation and sanitized evidence updates.

### Out

- Relaxing the rule that every nonconstant operation must support Neural Engine.
- Treating CPU/Neural Engine partitioning as ANE success.
- Changing the default Metal backend or enabling Core ML by default.
- Expanding ANE dispatch beyond the fixed FL2VA level-0/block-0 candidate.
- Changing public `h3.h` APIs or the released weight format.
- Shipping compiled Core ML models, checkpoints, raw traces, or private paths.
- Claiming observed placement, speed, RSS, or energy improvement in this loop.
- Making downstream benchmark/energy gates pass without their declared evidence.

## Requirements

### Diagnostics

- **R1:** Whenever the result destination is writable, a failed qualification
  result records exactly one first-failure stage
  from `setup`, `artifact`, `contract`, `receipt`, `load`, `compute_plan`,
  `eligibility`, `input`, `prediction`, `output`, `parity`, or `publication`,
  plus a stable reason code and human-readable message.
- **R2:** Eligibility failures additionally record the first rejected operation
  name and its supported/preferred device labels when Core ML provides them.
- **R3:** Missing context is encoded as `null`; diagnostics never fabricate a
  device, operation, or observed-placement claim.
- **R4:** The qualifier preserves the create-stage diagnostic even when its later
  prediction call observes an already-unavailable handle.
- **R5:** Any failure invalidates prior authority and leaves no passing receipt.
- **R5a:** If the result itself cannot be atomically published, the tool reports
  `publication/result_write_failed` on stderr and exits 2 with no receipt. A
  receipt publication failure rewrites the already-published result as
  `publication/receipt_write_failed` when possible and always removes authority.

### Artifact and Graph Contract

- **R6:** The converter and runtime continue to require canonical creator keys
  `version`, `variant`, `block_level`, `block_index`, `weight_prefix`,
  `boundary_dtype`, `shape`, and `source_sha256`.
- **R7:** The package-to-runtime gate validates the compiled model through the
  production metadata reader rather than inspecting package JSON alone.
- **R8:** The candidate accepts and returns F32 NDHWC
  `[1,1,256,256,128]`, preserves 32-group normalization with epsilon `1e-6`,
  OIDHW source-weight meaning, reflected spatial padding, two-frame front
  temporal zero padding, and the residual addition.
- **R9:** Because the fixed boundary depth is one, a convolution output can only
  depend on temporal kernel index two after two-front zero padding. The converter
  may use that exact OIHW slice as a 2D convolution only when a deterministic
  equivalence test covers nonzero weights in every temporal plane.
- **R10:** Group normalization may use per-group slicing, native normalization,
  and concatenation only when deterministic tests prove the same grouping,
  epsilon, affine scale/bias, and channel order as the Metal oracle.
- **R10a:** Production plan traversal uses a two-pass collector: the first pass
  counts recursively without storing operations, rejects count zero or count
  above the hard safety maximum 4096, and the second pass fills exactly the
  allocated count. Count/fill disagreement fails `compute_plan`; truncation is
  never accepted. Traversal also rejects nesting deeper than 64 blocks and uses
  overflow-checked allocation. The 4096-operation and 64-level bounds are
  resource-safety limits, not eligibility shortcuts.

### Eligibility and Authority

- **R11:** Non-shadow prediction remains unavailable unless every nonconstant
  operation has known Neural Engine support and a valid matching qualification
  receipt exists.
- **R12:** Unknown nonconstant-operation usage, CPU-only support, plan timeout,
  malformed structure, metadata drift, parity failure, and prediction failure
  all select the unchanged Metal result. A constant operation with nil device
  usage is counted for evidence but does not fail eligibility.
- **R13:** Eligibility and preferred-device data remain preflight labels. Only a
  retained Instruments trace can be called observed Neural Engine execution.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| The retained failing artifact is stale, not unloadable. | `H3_ANE_TRACE=1 ./h3_ane_qualification --model MiniMax-H3/FL2VA/video_vae/source --coreml-model /private/tmp/ane-u4-compiled/ane-u4-real.mlmodelc --output /private/tmp/ane-debug-result.json` | `2026-08-12T00:56:25Z` | MLModel load succeeded, but the production consumer rejected prefixed creator keys with `reason=contract`; no receipt was written. | Local compiled artifact and qualification trace; sanitized causal result retained in this spec. |
| The current decomposed graph is ineligible under the existing fail-closed policy. | `docs/evidence/ane-eligibility/design-plan-probe.m` compiled and run against the retained canonical baseline artifact. | `2026-08-12T00:57:56Z` | 35 nonconstant operations; 19 support Neural Engine and 16 are CPU-only. | Diagnosis trace summarized in this spec; the replacement candidate evidence is retained separately. |
| The exact 5D, canonical-metadata, real-weight candidate is compute-plan eligible before the production inventory cap. | Commands in `docs/evidence/ane-eligibility/2026-08-12-design-probe.json` using the two committed probe sources. | `2026-08-12T01:31:31Z` | Boundary is F32 `[1,1,256,256,128]`; all 149 nonconstant operations support Neural Engine; zero are CPU-only or unknown. | `docs/evidence/ane-eligibility/2026-08-12-design-probe.json` |
| The current production collector cannot load the candidate. | Production `h3_ane_qualification` against the exact candidate, with `H3_ANE_TRACE=1`. | `2026-08-12T01:28:49Z` | Candidate has 441 total operations but the runtime capacity is 256; it fails `compute_plan` before eligibility and writes no receipt. | `docs/evidence/ane-eligibility/2026-08-12-design-probe.json` |
| Compute-plan device usage is not observed execution. | Apple `MLComputePlan.deviceUsage(for:)` documentation inspected through the official developer site. | `2026-08-12T01:13:00Z` | The API returns anticipated compute-device usage for an operation; this spec retains Instruments as the observed-placement gate. | Apple Core ML documentation and `docs/ane-acceleration.md`. |

The live results are target- and compiler-specific preconditions, not portable
guarantees. Implementation must rerun the integration and eligibility commands;
the design probe alone cannot approve the produced artifact.

### Failure taxonomy

The first failing boundary owns the result. If cleanup or result publication also
fails, it is logged separately to stderr but does not replace the earlier failure;
publication is first only when all earlier work passed. Execution order fixes the
priority: setup and caller contract; compiled/source artifact hashing; receipt
validation for non-shadow use; Core ML load; creator metadata and I/O contract;
compute-plan structure/inventory; operation eligibility; input bridge; prediction;
output bridge; parity; then publication. Thus a bad receipt precedes creator
metadata inspection in non-shadow runtime, while authorized qualification skips
receipt authority and exposes creator-contract failures directly.

| Stage | Stable codes | Existing reason/source mapping | Structured context |
|---|---|---|---|
| `setup` | `disabled`, `os_unsupported`, `allocation_failed` | `DISABLED`, `OS`, host allocation | none |
| `artifact` | `compiled_model_unreadable`, `compiled_model_digest_failed`, `source_weights_unreadable`, `source_tensor_digest_failed` | directory/tensor fingerprint setup before Core ML create | relative artifact role and digest when available; no path |
| `contract` | `metadata_missing`, `metadata_mismatch`, `fingerprint_mismatch`, `shape_mismatch`, `dtype_mismatch` | `CONTRACT`, `FINGERPRINT`, `SHAPE`, `DTYPE` during create/load | mismatched field only; values are not serialized |
| `receipt` | `receipt_missing`, `receipt_malformed`, `receipt_digest_mismatch`, `receipt_invalid` | `RECEIPT` and receipt validator | none |
| `load` | `model_load_failed`, `model_load_exception` | `LOAD` after contract-independent Core ML load failure | none; NSError/path omitted |
| `compute_plan` | `plan_timeout`, `plan_load_failed`, `program_missing`, `main_missing`, `operation_inventory_empty`, `operation_inventory_limit_exceeded`, `operation_nesting_limit_exceeded`, `operation_inventory_changed` | plan callback/traversal failures currently folded into `ELIGIBILITY` | operation count/limit or nesting depth/limit when known |
| `eligibility` | `operation_usage_unknown`, `operation_not_neural_engine_supported`, `device_unknown` | `ELIGIBILITY` after a valid inventory | first operation and device labels when known |
| `input` | `input_shape_mismatch`, `input_dtype_mismatch`, `input_copy_failed` | pre-prediction `SHAPE`/`DTYPE` and input bridge | none |
| `prediction` | `prediction_failed`, `prediction_exception` | `PREDICTION` | none; NSError/path omitted |
| `output` | `output_shape_mismatch`, `output_dtype_mismatch`, `output_copy_failed`, `output_nonfinite` | `SHAPE`, `DTYPE`, `NONFINITE` after prediction | none |
| `parity` | `parity_metrics_nonfinite`, `parity_bounds_failed` | qualifier comparison after both backends return valid output | `max_abs` and `relative_l2` when finite |
| `publication` | `result_write_failed`, `receipt_write_failed` | atomic result/receipt writer | none; `result_write_failed` is stderr-only because no result can exist |

`placement` is not a qualification stage. It is the later Instruments evidence
gate in `ROADMAP.md`; this loop updates that document's gate-1 vocabulary to
`compute_plan` and `eligibility` while leaving observed placement as gate 3.

## Architecture

### Evidence flow

1. Conversion binds canonical metadata and the source-tensor fingerprint.
2. Compilation produces a temporary `.mlmodelc` artifact.
3. The production loader validates creator metadata and fixed I/O contract.
4. Compute-plan traversal records all operations and rejects the first unknown or
   CPU-only nonconstant operation.
5. Qualification runs the unchanged Metal oracle and Core ML prediction.
6. Only passing parity atomically publishes the digest-bound receipt.
7. Runtime non-shadow use validates that receipt; all other paths adopt Metal.

### Graph representation

The external boundary remains five-dimensional. Internally, the fixed singleton
depth dimension may be removed and restored with statically shaped operations.
Each four-channel group is independently normalized across its channel and two
spatial axes, then groups are concatenated in original channel order and receive
the released affine weights. Each 3×3×3 convolution uses the temporal plane that
is mathematically reachable at depth one and otherwise preserves released spatial
weights, bias, reflected padding, activation order, and residual behavior.

This representation is an implementation candidate, not an authority shortcut:
eligibility, equivalence, and real Metal parity must all pass independently.

### Diagnostic ownership

The backend handle owns the immutable first-unavailable diagnostic produced
during creation or prediction. Public and tool-facing snapshots copy that record;
later fallback accounting may increment counters but cannot replace its stage or
reason with a generic message. The qualifier serializes only bounded enums,
operation names, device labels, and messages—never private model paths.

The plan collector owns a bounded heap inventory rather than a fixed 256-entry
stack array. Two-pass count/fill behavior makes compiler growth observable and
prevents silent truncation; the handle frees the inventory after eligibility has
been reduced into its immutable diagnostic and summary statistics.

## Interface and Result Contract

The existing qualification CLI and runtime environment variables remain stable.
Failed `h3-ane-qualification/v1` results retain the existing string
`failure_reason` for compatibility and add:

```json
{
  "failure_stage": "eligibility",
  "failure_code": "operation_not_neural_engine_supported",
  "failure_operation": "ios17.reshape",
  "supported_devices": ["cpu"],
  "preferred_device": "cpu"
}
```

For non-eligibility stages, operation/device fields are `null`. Passing results
set every failure field, including `failure_reason`, to `null`. Device arrays use
the closed labels `cpu`, `gpu`, and `neural-engine`, in stable order. Unknown Core
ML device types are not serialized as invented labels; the relevant field is
`null` and the result fails closed.

## Integration

- The converter remains an offline pinned `uv` tool; the C runtime gains no
  Python dependency.
- The integration gate uses real `coremlcompiler`, the production Objective-C
  loader/plan traversal, and a bounded deterministic fixture graph.
- Real FL2VA qualification remains conditional on released local weights and
  target Apple Silicon, but the package/compiler/runtime contract gate is always
  runnable on supported macOS with Xcode and pinned packages available.
- `ROADMAP.md` gate 1 closes only when structured diagnostics pass. Gate 2 closes
  only on a real passing receipt. Gates 3–6 remain independently blocked until
  their own evidence exists.

## Testing

- Table-driven native tests for every diagnostic stage, absent operation/device
  context, first-error preservation, and stable JSON serialization.
- Negative tests for stale prefixed creator metadata at the compiled-runtime
  boundary, not only producer/consumer unit tests.
- Deterministic graph tests covering all three temporal kernel planes, every
  normalization group boundary, affine parameters, padding edges/corners,
  residual addition, and F32 boundary conversion.
- Compute-plan tests that enumerate every nonconstant operation and fail on CPU,
  GPU-only, unknown nonconstant usage, timeout, empty plans, count/fill drift,
  nesting above 64, and counts above 4096. Constant nil-usage is retained but
  accepted. A 441-operation eligible fixture must pass the production collector.
- Real target qualification against the unchanged Metal oracle with the existing
  `max_abs < 0.002` and `relative_l2 < 0.02` limits.
- Regression tests for default-off behavior, shadow output, pointer-identical
  Metal fallback, receipt invalidation, cancellation, and allocation failure.
- Full actual-Metal build/test verification after focused tests.

## Risks and Mitigations

- **Compiler drift:** Core ML may lower the same graph differently across OS or
  compiler versions. Pin tool versions, retain operation inventory, and fail
  closed on every produced artifact.
- **False temporal equivalence:** Dropping two kernel planes is valid only for the
  fixed depth-one/two-front-zero boundary. Keep the boundary fixed and test all
  planes; never generalize this converter to deeper inputs.
- **Normalization order drift:** Per-group slicing can reorder channels or change
  affine broadcasting. Test group boundaries and compare against the Metal oracle.
- **Operation-count overhead:** Thirty-two native normalization groups increase
  graph operation count. This loop establishes availability/parity, not speed;
  latency remains a later measured gate.
- **Eligibility overclaim:** Preferred Neural Engine is not actual placement.
  Preserve the terminology boundary and require Instruments for observed use.
- **Diagnostic leakage:** NSError text or paths could expose local details. Emit
  stable codes and bounded sanitized messages; never serialize paths.
- **Stale authority:** Artifact replacement could leave an old receipt. Keep
  digest binding, invalidate before qualification, and publish the receipt last.

## Success Criteria

1. Every qualification execution failure with a writable result destination is
   preserved in structured output; result-publication failure is preserved on
   stderr; and no failing case writes an authorizing receipt.
   - **Measured by**: `make h3_ane_tool_tests && python3 -m unittest discover -s tests -p 'test_ane_tools.py'`
2. The pinned package-to-compiler-to-production-runtime gate rejects stale
   metadata and accepts canonical metadata without substituting package inspection.
   - **Measured by**: `make h3_ane_integration_test`
3. The produced fixed-block candidate has no unknown or non-Neural-Engine-supported
   nonconstant operation on the target machine.
   - **Measured by**: `H3_ANE_TRACE=1 make h3_ane_integration_test`; the retained
     sanitized operation summary reports `cpu_only_nonconstant_operations: 0`,
     `unknown_nonconstant_operations: 0`, exactly `149` Neural Engine-supported
     nonconstant operations, and exactly `441` total operations for the pinned
     candidate/compiler/OS evidence tuple. Any compiler inventory drift requires
     refreshed evidence and requalification rather than automatic acceptance.
4. The real fixed FL2VA candidate passes Metal/Core ML parity and publishes one
   matching receipt.
   - **Measured by**: `make h3_ane_qualification && ./h3_ane_qualification --model MiniMax-H3/FL2VA/video_vae/source --coreml-model "$H3_ANE_MODEL" --output .release-loop/evidence/ane-qualification.json`; exit zero, `status: "passed"`, `max_abs < 0.002`, `relative_l2 < 0.02`, matching digests, and an existing receipt are required.
5. Default-off execution and every unavailable/error path still adopt unchanged
   Metal output with stable fallback accounting.
   - **Measured by**: `make h3_ane_tests && ./h3_ane_tests`
6. The complete repository remains green on actual Metal after the new backend
   candidate and diagnostics are built.
   - **Measured by**: `make clean && make -j8 && make test && make h3_ane_tests && ./h3_ane_tests`
7. No shipped artifact or documentation claims observed Neural Engine execution
   from eligibility, configuration, preference, or parity alone.
   - **Measured by**: reviewer rubric over result JSON, trace labels,
     `docs/ane-acceleration.md`, and committed evidence; pass requires the terms
     `eligible`/`preferred` for compute-plan data and reserves `observed` for an
     Instruments trace overlapping prediction.
8. The scope remains the fixed private FL2VA block and does not change the public
   library API or default backend selection.
   - **Measured by**: `git diff main...HEAD -- h3.h` is empty, and focused tests
     assert zero Core ML load attempts when `H3_ANE_MODEL` is unset.

## Open Decisions

- **Implementation-owned:** Choose the smallest native normalization graph that
  preserves R8–R10 and passes the actual compiler inventory; the probed
  slice/layer-norm/concat form is the grounded baseline, not a mandate against an
  equally proven simpler form.
- **Implementation-owned:** Define the exact sanitized integration summary path
  under `.release-loop/evidence/`; it must reuse the v2 fields in the committed
  design probe while raw compiled artifacts and traces remain local.
- **Operator-owned after this loop:** Whether to proceed from a passing receipt to
  observed placement, latency, RSS, and energy gates. Those measurements cannot be
  inferred or pre-approved here.
