# Experimental ANE eligibility and shadow measurement

The Apple Neural Engine (ANE) path is a default-off experiment for FL2VA visual
encoder level 0, block 0. Metal remains the default backend, fallback, and
numerical oracle. The experiment does not change the public `h3.h` API.

## Current evidence and claim boundary

The current fixed artifact passes the production compute-plan inventory:

| Inventory field | Observed value |
|---|---:|
| Total operations | 441 |
| Constant operations | 292 |
| Nonconstant operations | 149 |
| Nonconstant operations supporting Neural Engine | 149 |
| CPU-only nonconstant operations | 0 |
| GPU-only nonconstant operations | 0 |
| Unknown nonconstant operations | 0 |
| Constants with no device usage | 292 |

This is **eligibility** evidence only. `MLComputePlan` reports anticipated device
support and preferred devices; it does not report runtime placement.

The real artifact still fails strict qualification:

- `max_abs = 0.19216197729110718`
- `relative_l2 = 0.038400878187031535`
- strict bounds: `max_abs < 0.002`, `relative_l2 < 0.02`
- diagnostic: `parity/parity_bounds_failed`
- receipt: `null`

The approved `shadow-measurement-v1` profile passes its finite provisional
bounds, `max_abs < 0.25` and `relative_l2 < 0.05`, with the same metrics. Its
result is always `authority: false` and `receipt: null`. Core ML output remains
discarded; Metal output remains authoritative.

Do not describe shadow threshold success as parity qualification, production
equivalence, observed ANE execution, or authorization. No Instruments trace has
yet shown Neural Engine activity overlapping prediction, so runtime placement
is not observed. Latency, process-memory, and energy gates also remain blocked.

## Fixed graph and runtime contract

The experiment applies to one immutable external boundary:

| Field | Value |
|---|---|
| Variant | `FL2VA` |
| Block | level `0`, block `0` |
| Weight prefix | `encoder.down.0.block.0` |
| Input and output | F32 NDHWC `[1,1,256,256,128]` |
| Runtime floor | macOS 14.4 |
| Core ML compute units | CPU and Neural Engine |

Internally, the converter removes only the singleton depth dimension. It
preserves 32-group normalization with epsilon `1e-6`, affine scale and bias,
channel order, reflected one-pixel spatial padding, SiLU, two convolutions, and
the residual addition. With input depth one and two frames of front zero
padding, only temporal OIDHW kernel plane two can affect the output, so the
fixed graph uses that exact OIHW plane for each 2D convolution and restores the
depth dimension at the output. This reduction is not valid for deeper inputs.

Production compute-plan traversal is two-pass. It first counts recursively,
then allocates and fills the exact count. It rejects:

- zero operations or more than 4096 operations;
- nesting deeper than 64 blocks;
- allocation overflow or failure; and
- any count/fill disagreement.

The 4096-operation and 64-level bounds are resource-safety limits, not
eligibility shortcuts. After a structurally valid inventory, every nonconstant
operation must have known Neural Engine support. A constant with nil device
usage is counted but does not fail eligibility.

### Runtime environment

| Variable | Effect |
|---|---|
| `H3_ANE_MODEL=/absolute/path/model.mlmodelc` | Explicit opt-in. When unset, no Core ML model is loaded. |
| `H3_ANE_SHADOW=1` | Runs Core ML diagnostically but always returns Metal output. Only the exact value `1` enables it. |
| `H3_ANE_TRACE=1` | Prints operation support and preferred-device diagnostics. Only the exact value `1` enables it. |
| `H3_ANE_WEIGHT_DIR=/absolute/source` | Supplies released FL2VA source weights to the real and shadow Make targets and benchmark tool. |

Non-shadow runtime use also requires the strict receipt at:

```text
<MODEL.mlmodelc>.qualification.json
```

The receipt binds the compiled-directory digest, source-tensor fingerprint,
test vector, timestamp, and strict metrics. A missing, malformed, failed, stale,
or mismatched receipt selects Metal. Shadow execution never creates or preserves
this authority.

## Canonical metadata and local artifacts

The converter writes these creator-defined metadata strings:

| Key | Canonical value |
|---|---|
| `version` | `1` |
| `variant` | `FL2VA` |
| `block_level` | `0` |
| `block_index` | `0` |
| `weight_prefix` | `encoder.down.0.block.0` |
| `boundary_dtype` | `F32` |
| `shape` | `1,1,256,256,128` |
| `source_sha256` | canonical source-tensor fingerprint |
| `h3_ane_boundary_layout` | `NDHWC` |
| `h3_ane_weight_layout` | `OIDHW` |
| `h3_ane_group_count` | `32` |
| `h3_ane_epsilon` | `1e-6` |
| `h3_ane_temporal_padding` | `front=2,back=0,mode=constant` |
| `h3_ane_spatial_padding` | `1,1,1,1,mode=reflect` |

The source fingerprint hashes the eight selected tensors in sorted name order,
including name, dtype identifier, rank, shape, payload length, and raw bytes.
The compiled-model digest hashes regular files in sorted relative-path order.
Unsafe paths, unsupported file types, and every symlink are rejected.

Weights, `.mlpackage`, `.mlmodelc`, receipts, media, and raw Instruments traces
remain local and gitignored. Commit only bounded sanitized result summaries;
never commit absolute private paths, device identifiers, checkpoints, compiled
models, or raw traces.

Core ML Tools remains outside the C runtime and default build. All conversion
and integration targets use this exact isolated environment:

```sh
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 \
  --with coremltools==9.0 \
  --with numpy==2.3.2 \
  --with safetensors==0.6.2 \
  scripts/convert_ane_visual_block.py --help
```

If the packages are absent globally, that is expected. If uv cannot resolve or
reuse the pinned packages, report dependency unavailability; do not label it an
ANE, graph, or qualification failure.

## Structured qualification result

Build and inspect the qualifier:

```sh
make h3_ane_qualification h3_ane_integration_probe h3_ane_tool_tests
./h3_ane_qualification --help
python3 scripts/run_ane_integration.py --help
```

The strict qualifier writes `h3-ane-qualification/v1`. These fields are stable:

```json
{
  "schema": "h3-ane-qualification/v1",
  "status": "passed|failed",
  "model_sha256": "hex-or-empty",
  "source_sha256": "hex-or-empty",
  "test_vector": "xorshift32-v1",
  "qualified_at": "UTC-or-empty",
  "max_abs": 0.0,
  "relative_l2": 0.0,
  "receipt_path": "compiled-model.qualification.json|null",
  "failure_reason": "message|null",
  "failure_stage": "stage|null",
  "failure_code": "code|null",
  "failure_operation": "bounded-name|null",
  "supported_devices": ["cpu", "gpu", "neural-engine"],
  "preferred_device": "cpu|gpu|neural-engine|null",
  "observed_count": 0,
  "limit": 0
}
```

Context fields are `null` when the failing boundary does not provide them.
Device arrays use only `cpu`, `gpu`, and `neural-engine`, in that order. A
successful strict result sets every failure field to `null`. If the result
cannot be atomically published, no result exists: stderr reports
`publication/result_write_failed`, the process exits 2, and no receipt is
written. If receipt publication fails, the result is rewritten as
`publication/receipt_write_failed` when possible and authority remains absent.

The closed failure stages and codes are:

| Stage | Codes |
|---|---|
| `setup` | `disabled`, `os_unsupported`, `allocation_failed` |
| `artifact` | `compiled_model_unreadable`, `compiled_model_digest_failed`, `source_weights_unreadable`, `source_tensor_digest_failed` |
| `contract` | `metadata_missing`, `metadata_mismatch`, `shape_mismatch`, `dtype_mismatch` |
| `receipt` | `receipt_missing`, `receipt_malformed`, `fingerprint_mismatch`, `receipt_digest_mismatch`, `receipt_invalid` |
| `load` | `model_load_failed`, `model_load_exception` |
| `compute_plan` | `allocation_failed`, `plan_timeout`, `plan_load_failed`, `program_missing`, `main_missing`, `operation_inventory_empty`, `operation_inventory_limit_exceeded`, `operation_nesting_limit_exceeded`, `operation_inventory_changed` |
| `eligibility` | `operation_usage_unknown`, `operation_not_neural_engine_supported`, `device_unknown` |
| `input` | `input_shape_mismatch`, `input_dtype_mismatch`, `input_copy_failed` |
| `prediction` | `prediction_failed`, `prediction_exception` |
| `output` | `allocation_failed`, `output_shape_mismatch`, `output_dtype_mismatch`, `output_copy_failed`, `output_nonfinite` |
| `parity` | `parity_metrics_nonfinite`, `parity_bounds_failed` |
| `publication` | `result_write_failed`, `receipt_write_failed` |

`placement` is deliberately not a qualification stage.

## One-command integration targets

### Synthetic package/compiler/runtime gate

This target needs no released weights. It generates deterministic exact-shape
weights, converts and compiles the package, loads it through the production
metadata and compute-plan consumer, and publishes a sanitized
`h3-ane-integration/v1` summary:

```sh
make h3_ane_integration_test
```

A passing summary has `mode: "synthetic"`, inventory `441/149/149/0`, and
`diagnostic`, `parity`, and `receipt` set to `null`. Synthetic success proves
the package/compiler/production-reader gate; it does not qualify real weights or
authorize runtime output.

The `h3-ane-integration/v1` summary has this mode-dependent field contract:

| Field | Synthetic | Strict real | Shadow |
|---|---|---|---|
| `schema` | `h3-ane-integration/v1` | same | same |
| `status` | `passed|failed` | `passed|failed` | `passed|failed` |
| `mode` | `synthetic` | `real` | `shadow` |
| `profile` | `null` | `null` | `shadow-measurement-v1` |
| `authority` | `null` | `null` | always `false` |
| `source_sha256` | digest or `null` on failure | same | same |
| `inventory` | eight-field inventory or `null` | same | same |
| `diagnostic` | `{stage,code,message}` or `null` | same | same |
| `parity` | always `null` | `{max_abs,relative_l2}` or `null` | same shape, never authority |
| `receipt` | always `null` | validated receipt subset or `null` | always `null` |
| `artifacts` | `{model_sha256,source_sha256}` or `null` | same | same |
| `stages` | completed child exit codes | same | same |
| `measurement_started` | absent | absent | boolean when qualification reports it |
| `authority_state` | absent | absent | `invalidated`, `unchanged`, or absent before that boundary |

The eight inventory fields are `total`, `constant`, `nonconstant`,
`neural_engine_supported`, `cpu_only`, `gpu_only`, `unknown_nonconstant`, and
`constant_nil_usage`. In this document, `441/149/149/0` means total /
nonconstant / Neural-Engine-supported / CPU-only-and-unknown (both zero).

### Strict real qualification

The explicit real target requires released weights:

```sh
export H3_ANE_WEIGHT_DIR="$PWD/MiniMax-H3/FL2VA/video_vae/source"
make h3_ane_real_qualification_test
```

Without `H3_ANE_WEIGHT_DIR`, Make exits 2 before Python and reports
`H3_ANE_WEIGHT_DIR is required for h3_ane_real_qualification_test`. Missing
weights are a prerequisite failure, not an ANE failure.

Strict mode is the exclusive authority path. It uses finite
`max_abs < 0.002` and `relative_l2 < 0.02`, publishes a digest-bound receipt
only after both pass, and alone can authorize non-shadow Core ML output. The
current real target exits nonzero with `parity/parity_bounds_failed`, the
metrics shown above, and `receipt: null`.

### Non-authorizing shadow measurement

Run the approved shadow profile with the same released weights:

```sh
export H3_ANE_WEIGHT_DIR="$PWD/MiniMax-H3/FL2VA/video_vae/source"
make h3_ane_shadow_measurement_test
```

The Make target invokes the qualifier with `--shadow-only`. Direct use against
an existing compiled model is:

```sh
./h3_ane_qualification --shadow-only \
  --model "$H3_ANE_WEIGHT_DIR" \
  --coreml-model "$H3_ANE_MODEL" \
  --output /absolute/local/path/shadow-qualification.json
```

Both interfaces apply finite `max_abs < 0.25` and `relative_l2 < 0.05`. A
passing qualifier result includes:

```json
{
  "profile": "shadow-measurement-v1",
  "status": "passed",
  "authority": false,
  "measurement_started": true,
  "authority_state": "invalidated",
  "bounds": {"max_abs": 0.25, "relative_l2": 0.05},
  "threshold_outcome": true,
  "receipt_path": null
}
```

The integration summary uses `mode: "shadow"`, the same profile and authority
fields, inventory, parity metrics, `receipt: null`, and per-stage exit statuses.
Passing shadow measurement only allows local exploratory placement, latency,
memory, and energy collection while Core ML output is discarded. It does not
pass any of those evidence gates by itself.

Before measuring or changing authority, shadow mode proves that the receipt
directory supports a link-safe same-directory quarantine using disposable
sibling entries. If this preflight fails:

- measurement does not start;
- an existing receipt and authority state remain byte-for-byte unchanged;
- the process exits 2;
- a writable result records `measurement_started: false`,
  `authority_state: "unchanged"`, `authority: false`, `receipt_path: null`,
  `failure_stage: "receipt"`, and `failure_code: "receipt_invalid"`; and
- no placement, parity, latency, memory, or energy evidence from that invocation
  is accepted.

If preflight succeeds, the live receipt pathname is invalidated before
measurement. Success, threshold failure, nonfinite metrics, publication failure,
or cancellation never publishes replacement authority.

## Runtime shadow and observed placement

After the shadow target passes, its default local compiled model is
`/private/tmp/h3-ane-shadow-measurement/visual-block.mlmodelc`. Use a real
256-by-256 first-frame condition so the fixed block executes:

```sh
export H3_ANE_MODEL=/private/tmp/h3-ane-shadow-measurement/visual-block.mlmodelc
export FIRST_FRAME=/absolute/path/to/first-frame-256.png
test -f "$FIRST_FRAME"
test "$(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height -of csv=s=x:p=0 \
  "$FIRST_FRAME")" = "256x256"

env -u H3_ANE_MODEL -u H3_ANE_SHADOW -u H3_ANE_TRACE \
./h3 -d ./MiniMax-H3 \
  -p "A slow camera move around the supplied first frame." \
  --first-frame "$FIRST_FRAME" \
  --width 256 --height 256 --frames 22 --steps 4 \
  --layers 50 --reuse 1 \
  -o outputs/ane-metal-baseline.mp4

H3_ANE_MODEL="$H3_ANE_MODEL" H3_ANE_SHADOW=1 H3_ANE_TRACE=1 \
./h3 -d ./MiniMax-H3 \
  -p "A slow camera move around the supplied first frame." \
  --first-frame "$FIRST_FRAME" \
  --width 256 --height 256 --frames 22 --steps 4 \
  --layers 50 --reuse 1 \
  -o outputs/ane-shadow.mp4
```

The baseline and shadow commands use the same real first frame, prompt, and
generation geometry. The baseline explicitly removes every ANE opt-in variable,
so it exercises the unchanged Metal visual-conditioning path.

`eligible` means every nonconstant operation advertises Neural Engine support.
`preferred` means the compute plan names a preferred device. Neither word means
runtime placement. Use `observed Neural Engine` only for a retained Instruments
trace showing Neural Engine activity overlapping the Core ML prediction
interval. The trace command must keep `H3_ANE_SHADOW=1`; the generated request
still returns Metal output.

## Strict-only benchmark and independent evidence gates

`h3_ane_bench` creates a non-shadow handle, so it requires a passing strict
receipt. The current artifact has no receipt; these commands are future gates,
not current shadow evidence.

After strict qualification succeeds, record 20 alternating pairs and analyze
transfer-inclusive latency:

```sh
make h3_ane_bench
./h3_ane_bench --backend ab --coreml-model "$H3_ANE_MODEL" \
  --warmup 2 --pairs 20 --output /absolute/local/path/ane-ab.json
python3 scripts/analyze_ane_benchmark.py /absolute/local/path/ane-ab.json
```

Latency passes only with at least 20 complete alternating pairs, a positive 95%
bootstrap confidence-interval lower bound for paired `Metal - Core ML`, and at
least 5% median transfer-inclusive improvement.

Record process memory independently:

```sh
/usr/bin/time -l ./h3_ane_bench --backend metal --pairs 20 \
  --output /absolute/local/path/ane-metal.json 2> /absolute/local/path/ane-metal-time.txt
/usr/bin/time -l ./h3_ane_bench --backend coreml \
  --coreml-model "$H3_ANE_MODEL" --pairs 20 \
  --output /absolute/local/path/ane-coreml.json 2> /absolute/local/path/ane-coreml-time.txt
```

Process memory passes only when Core ML maximum resident set size grows no more
than 5% relative to matched Metal. GPU allocation statistics cannot substitute.

Placement requires an Instruments trace with Neural Engine activity overlapping
prediction. Energy requires a named exported counter and unit with at least 5%
paired-median improvement on the same workload. Eligibility, preferred device,
strict parity, a receipt, or shadow threshold success cannot substitute for
observed placement, latency, process memory, or energy evidence.

| Gate | Required evidence |
|---|---|
| Strict qualification | Matching digest-bound receipt; `max_abs < 0.002`; `relative_l2 < 0.02`. |
| Observed placement | Retained Instruments trace showing Neural Engine activity overlapping prediction. |
| Latency | 20+ complete alternating pairs; positive paired 95% CI lower bound; at least 5% median transfer-inclusive improvement. |
| Process memory | Matched `/usr/bin/time -l`; Core ML maximum RSS growth no greater than 5%. |
| Energy | One named, unit-bearing Instruments counter; at least 5% paired-median improvement. |
