# Experimental ANE acceleration

This document describes the default-off Apple Neural Engine (ANE) measurement
harness for FL2VA visual encoder level 0, block 0. It is an experiment, not a
production backend or a performance claim. Metal remains the default, fallback,
and numerical oracle.

## Current result

The harness, converter, compiler path, qualification tool, benchmark tool, and
analyzer are implemented. A real conversion and `coremlcompiler` compile both
succeeded with the local FL2VA weights:

- source fingerprint:
  `ad7b9b6432fc3c31c095bd6918c47ea5d6d0f145f4fae33fd46e0fc2738ce163`
- compiled-model digest:
  `eb9aa723703364943e8171003f4445f10673f6b5b889d45a76d135375990ebe1`

Real qualification then failed closed with `ANE backend is unavailable`. The
failure is retained in `.release-loop/evidence/U4/real-qualification.json`.
The tool did not create a passing `<MODEL.mlmodelc>.qualification.json`
sidecar. Therefore:

- the harness is ready for further measurement;
- real numerical qualification has not passed;
- ANE placement and performance have not been established; and
- no acceleration, memory, or energy claim exists.

Do not treat build success, conversion, compilation, configuration,
`MLComputePlan` eligibility, preferred CPU placement, or mixed placement as ANE
execution evidence.

## Runtime contract

The experiment applies only to this boundary:

| Field | Value |
|---|---|
| Model variant | `FL2VA` |
| Block | level `0`, block `0` |
| Weight prefix | `encoder.down.0.block.0` |
| Boundary shape | NDHWC `[1,1,256,256,128]` |
| Boundary dtype | `F32` |
| Runtime floor | macOS 14.4 |
| Core ML compute units | CPU and Neural Engine |

Every non-constant operation must list the Neural Engine as a supported device
before prediction is attempted. Preferred CPU or mixed placement is recorded,
but it does not establish that prediction ran on ANE.

### Environment variables

| Variable | Effect |
|---|---|
| `H3_ANE_MODEL=/absolute/path/model.mlmodelc` | Explicitly opts into the compiled model. When unset, no Core ML model is loaded. Use an absolute path so the model, receipt, benchmark, and trace all identify the same artifact. |
| `H3_ANE_SHADOW=1` | Runs Core ML diagnostically but always adopts the unchanged Metal result. Shadow mode may inspect an unqualified model because its output is never adopted. |
| `H3_ANE_TRACE=1` | Prints each compute-plan operation name, constant flag, supported-device bit mask, and preferred-device bit mask to stderr. |
| `H3_ANE_WEIGHT_DIR=/path/to/source` | Selects the source-weight directory for `h3_ane_bench`; the default is `MiniMax-H3/FL2VA/video_vae/source`. |

Only the exact string `1` enables shadow or trace mode.

### Canonical model metadata

The converter writes these strings into the Core ML model's
`userDefinedMetadata`:

| Key | Canonical value |
|---|---|
| `version` | `1` |
| `variant` | `FL2VA` |
| `block_level` | `0` |
| `block_index` | `0` |
| `weight_prefix` | `encoder.down.0.block.0` |
| `boundary_dtype` | `F32` |
| `shape` | `1,1,256,256,128` |
| `source_sha256` | source-tensor fingerprint |
| `h3_ane_boundary_layout` | `NDHWC` |
| `h3_ane_weight_layout` | `OIDHW` |
| `h3_ane_group_count` | `32` |
| `h3_ane_epsilon` | `1e-6` |
| `h3_ane_temporal_padding` | `front=2,back=0,mode=constant` |
| `h3_ane_spatial_padding` | `1,1,1,1,mode=reflect` |

Runtime validates the version, variant, block coordinates, weight prefix,
boundary dtype and shape, and source fingerprint before prediction.

### Fingerprints and qualification receipt

The source fingerprint is a SHA-256 over the eight selected tensors in sorted
name order. The canonical stream includes the tensor name, dtype identifier,
rank and shape, payload length, and raw payload bytes, so changing the active
weights changes the fingerprint.

The compiled-model digest is a SHA-256 over the compiled directory's regular
files in sorted relative-path order. Unsafe paths, unsupported file types, and
symlinks that escape the model directory are rejected. Changing compiled bytes
invalidates the digest.

Non-shadow execution requires the fixed receipt path:

```text
<MODEL.mlmodelc>.qualification.json
```

The receipt binds the compiled digest to the source fingerprint and records its
schema version, test-vector identity, qualification timestamp, maximum absolute
error, relative L2 error, and passing status. Qualification passes only when
`max_abs < 0.002` and `relative_l2 < 0.02`. A missing, malformed, failed, stale,
or mismatched receipt selects Metal. The qualification command invalidates an
old receipt before testing and writes a new sidecar atomically only on pass.

## Build and inspect the tools

```sh
make h3_ane_qualification h3_ane_bench h3_ane_tool_tests
./h3_ane_qualification --help
./h3_ane_bench --help
python3 scripts/analyze_ane_benchmark.py --help
```

The ANE tools do not change the default `make` or runtime selection. The C
runtime has no Python dependency.

## Convert and compile the block

Core ML Tools is deliberately isolated from the repository and C runtime. Use
the pinned environment for every conversion:

```sh
uv run --python 3.12 \
  --with coremltools==9.0 \
  --with numpy==2.3.2 \
  --with safetensors==0.6.2 \
  scripts/convert_ane_visual_block.py \
  --weights MiniMax-H3/FL2VA/video_vae/source \
  --output build/ane-visual-block.mlpackage
```

Compile the emitted package into an otherwise empty output directory:

```sh
mkdir -p build/coreml
xcrun coremlcompiler compile \
  build/ane-visual-block.mlpackage \
  build/coreml
export H3_ANE_MODEL="$PWD/build/coreml/ane-visual-block.mlmodelc"
```

For atomic replacement of a named compiled destination, the converter also
supports `--compile-output build/ane-visual-block.mlmodelc`. It invokes the same
`coremlcompiler compile` command in a temporary sibling directory and publishes
the single resulting `.mlmodelc` only after a successful compile.

If `coremltools`, NumPy, or safetensors is absent globally, that is expected.
`uv run --with` installs or reuses them in an isolated uv environment. An
offline machine without the packages in its uv cache fails before conversion;
this is a dependency-availability failure, not a runtime or ANE result.

## Qualify numerical parity

Build the native qualifier, then run it against the same source weights and
compiled directory:

```sh
make h3_ane_qualification
./h3_ane_qualification \
  --model MiniMax-H3/FL2VA/video_vae/source \
  --coreml-model "$H3_ANE_MODEL" \
  --output .release-loop/evidence/ane-qualification.json
```

The qualifier generates a deterministic `xorshift32-v1` input, runs the exact
Metal block and Core ML, and records both parity metrics. Exit zero plus a
`status: "passed"` result and the matching sidecar prove offline parity. A
failed result or absent receipt means non-shadow execution remains unauthorized.

The optional end-to-end visual-encoder test also needs
`misc/fixtures/h3_real_video_encoder_256.safetensors`. That private, ignored
fixture is absent in this checkout. `make test` reports a skip when either the
fixture or released visual-encoder weights are absent; a skip is not parity
evidence.

## Run shadow diagnostics

Shadow mode does not require a passing receipt because it always returns Metal
output. Use a 256-square first-frame conditioning path so the fixed block is a
candidate:

```sh
H3_ANE_MODEL="$H3_ANE_MODEL" \
H3_ANE_SHADOW=1 \
H3_ANE_TRACE=1 \
./h3 -d ./MiniMax-H3 \
  -p "A slow camera move around the supplied first frame." \
  --first-frame input.png \
  --width 256 --height 256 --frames 22 --steps 4 \
  --layers 50 --reuse 1 \
  -o outputs/ane-shadow.mp4
```

Trace lines report compute-plan support and preferred-device masks. They are
preflight diagnostics only. Shadow parity and an eligible plan still do not
prove ANE placement.

## Record alternating A/B latency

Do not run a Core ML benchmark until qualification has created a matching
passing receipt. The benchmark uses two warm-ups per backend by default and
alternates Metal/Core ML (`AB`) on even pairs and Core ML/Metal (`BA`) on odd
pairs:

```sh
export H3_ANE_WEIGHT_DIR="$PWD/MiniMax-H3/FL2VA/video_vae/source"
./h3_ane_bench \
  --backend ab \
  --coreml-model "$H3_ANE_MODEL" \
  --warmup 2 \
  --pairs 20 \
  --output .release-loop/evidence/ane-ab.json
python3 scripts/analyze_ane_benchmark.py \
  .release-loop/evidence/ane-ab.json
```

The JSON records the selected backend, placement summary, Metal time, Core ML
input/prediction/output and transfer-inclusive total time, parity metrics, all
post-warm-up samples, and peak process RSS. The analyzer rejects incomplete or
nonalternating samples and fewer than 20 pairs. It exits zero only when both:

- the 95% deterministic bootstrap confidence-interval lower bound for paired
  `Metal - Core ML` transfer-inclusive latency is positive; and
- median transfer-inclusive latency improves by at least 5%.

## Record process memory

Capture maximum resident set size independently for each backend and retain
stderr with the JSON evidence:

```sh
/usr/bin/time -l ./h3_ane_bench \
  --backend metal --pairs 20 \
  --output .release-loop/evidence/ane-metal.json \
  2> .release-loop/evidence/ane-metal-time.txt

/usr/bin/time -l ./h3_ane_bench \
  --backend coreml --coreml-model "$H3_ANE_MODEL" --pairs 20 \
  --output .release-loop/evidence/ane-coreml.json \
  2> .release-loop/evidence/ane-coreml-time.txt
```

Use the `maximum resident set size` values from `/usr/bin/time -l`, not GPU-only
allocation statistics. A process-memory claim passes only when Core ML maximum
RSS is no more than 5% above the matched Metal value.

## Capture placement and energy with Instruments

First retain a default Metal/MPSGraph generation baseline. Unset all ANE
variables so the trace cannot accidentally opt into Core ML:

```sh
env -u H3_ANE_MODEL -u H3_ANE_SHADOW -u H3_ANE_TRACE \
xctrace record \
  --template 'Metal System Trace' \
  --output .release-loop/evidence/h3-metal-baseline.trace \
  --launch -- ./h3 -d ./MiniMax-H3 \
  -p "A red fox walks through fresh snow." \
  --width 256 --height 256 --frames 22 --steps 4 \
  --layers 50 --reuse 1 \
  -o outputs/h3-metal-baseline.mp4
```

After qualification passes, record the focused alternating workload with the
installed Core ML template:

```sh
xctrace record \
  --template 'Core ML' \
  --output .release-loop/evidence/ane-placement.trace \
  --env H3_ANE_MODEL="$H3_ANE_MODEL" \
  --env H3_ANE_WEIGHT_DIR="$H3_ANE_WEIGHT_DIR" \
  --launch -- ./h3_ane_bench \
  --backend ab --coreml-model "$H3_ANE_MODEL" \
  --warmup 2 --pairs 20 \
  --output .release-loop/evidence/ane-instruments-ab.json
```

An ANE placement claim requires retained Instruments evidence showing Neural
Engine activity overlapping the measured Core ML prediction intervals. Model
configuration, device support, `placement_summary`, and CPU or mixed preferred
placement are insufficient.

Record energy separately over the same A/B workload. On macOS, use the Core ML
template with the Neural Engine instrument; the installed `Power Profiler`
template is not supported for a macOS target:

```sh
xctrace record \
  --template 'Core ML' \
  --instrument 'Neural Engine' \
  --output .release-loop/evidence/ane-energy.trace \
  --env H3_ANE_MODEL="$H3_ANE_MODEL" \
  --env H3_ANE_WEIGHT_DIR="$H3_ANE_WEIGHT_DIR" \
  --launch -- ./h3_ane_bench \
  --backend ab --coreml-model "$H3_ANE_MODEL" \
  --warmup 2 --pairs 20 \
  --output .release-loop/evidence/ane-energy-ab.json
```

Open the retained trace in Instruments and export one available energy counter
for every pair. Record its exact counter name and unit with the exported data.
If this Xcode/macOS combination exposes placement/activity but no energy
counter, the energy gate remains unverified; do not substitute utilization or
duration. An energy claim passes only when the same counter's paired median
improves by at least 5%. Latency success cannot stand in for energy evidence.

## Independent evidence gates

These gates are independent; failure or absence of one cannot be replaced by a
different successful measurement.

| Gate | Passing evidence |
|---|---|
| Parity | Passing receipt bound to the active source and compiled digests; `max_abs < 0.002` and `relative_l2 < 0.02`. |
| Placement | Retained Instruments trace showing Neural Engine activity overlapping Core ML prediction. |
| Latency | At least 20 complete alternating pairs; positive 95% CI lower bound for paired `Metal - Core ML`; at least 5% median transfer-inclusive improvement. |
| Process memory | Matched `/usr/bin/time -l` maximum RSS; Core ML growth no greater than 5%. |
| Energy | One named, unit-bearing exported Instruments counter; at least 5% paired-median improvement. |

## Fallback reasons and statistics

Every failure falls back to the unchanged Metal block using the immutable
original input. Core ML writes to separate storage and is adopted only after all
online structural checks pass. Shadow mode always adopts Metal.

The stable `h3_ane_reason` values are:

| Reason | Meaning |
|---|---|
| `H3_ANE_REASON_NONE` | The last ANE operation completed without a fallback. |
| `H3_ANE_REASON_DISABLED` | No matching explicit opt-in/model path was supplied. |
| `H3_ANE_REASON_OS` | The process is running below macOS 14.4. |
| `H3_ANE_REASON_CONTRACT` | Version, variant, block identity, weight prefix, or other model contract data is incompatible. |
| `H3_ANE_REASON_FINGERPRINT` | Source or compiled-artifact fingerprinting failed or did not match. |
| `H3_ANE_REASON_RECEIPT` | The fixed qualification receipt is missing, invalid, failed, stale, or mismatched. |
| `H3_ANE_REASON_ELIGIBILITY` | The compute plan is unavailable or a non-constant operation does not support Neural Engine. |
| `H3_ANE_REASON_LOAD` | The Core ML backend is incomplete or the model failed to load. |
| `H3_ANE_REASON_PREDICTION` | Prediction, host transfer, or replacement-output allocation failed. |
| `H3_ANE_REASON_SHAPE` | The fixed count or `[1,1,256,256,128]` shape does not match. |
| `H3_ANE_REASON_DTYPE` | The boundary is not F32. |
| `H3_ANE_REASON_NONFINITE` | Prediction produced NaN or infinity. |

The operator-visible `h3_ane_stats` fields are:

| Stat | Meaning |
|---|---|
| `load_seconds` | Core ML model-load time. |
| `input_seconds` | Host input preparation/transfer time for the last prediction. |
| `prediction_seconds` | Core ML prediction time for the last prediction. |
| `output_seconds` | Output transfer time for the last prediction. |
| `attempts` | Total dispatch attempts. |
| `predictions` | Successful structurally valid Core ML predictions. |
| `fallbacks` | Attempts that selected or returned Metal. |
| `last_reason` | Stable reason for the last fallback, or `NONE`. |
| `preferred_device` | Bit mask accumulated from compute-plan preferred devices: CPU `0x1`, GPU `0x2`, Neural Engine `0x4`. |
| `shadow` | Whether the handle is diagnostic shadow mode. |

Benchmark evidence exposes the transfer phases, placement summary, parity
metrics, sample order, and `peak_rss_bytes`. `H3_ANE_TRACE=1` exposes the
operation-level support/preference details needed to interpret the masks.
