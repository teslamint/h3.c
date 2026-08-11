---
title: Experimental Apple Neural Engine Acceleration
status: approved
date: 2026-08-11
schema: spec/v1
---

# Experimental Apple Neural Engine Acceleration Design

_Created 2026-08-11._

## Overview

Add a default-off experimental Core ML measurement harness for one fixed
visual-encoder residual block. The release outcome is a safe, reproducible
backend experiment—not a performance claim. It enables separate qualification
of numerical fidelity and measurement of real Apple Neural Engine placement,
transfer cost, latency, energy, and process memory against unchanged Metal. The
experiment must fail closed to Metal and must not claim ANE acceleration without
placement evidence and quantitative qualification.

## User Scenarios

### S1: Establish the zero-change baseline

A developer runs the existing 256-pixel visual-encoder parity workload under
Instruments before enabling the experiment. They determine whether current
MPSGraph execution already produces Neural Engine activity and retain the trace
as baseline evidence.

### S2: Opt into the experimental block

A developer supplies a compiled Core ML model and explicitly enables the
experimental backend for the fixed level-0/block-0 visual-encoder block. Normal
CLI generation and library callers remain on Metal when the option is absent.

### S3: Receive safe fallback

If the model cannot load, its fingerprint does not match the active weights, the
input shape or dtype is unsupported, prediction fails, or online structural
validation fails, the same request runs through the unchanged Metal block. The
failed Core ML attempt cannot partially mutate the Metal input or output.

### S4: Compare backends reproducibly

A developer runs a focused parity/benchmark command that reports selected
backend, Core ML prediction and transfer time, Metal timing, placement summary,
peak memory, max absolute error, and relative L2 error. Results from alternating
warm runs can be exported for paired analysis.

## Scope

### In

- A private C API backed by an Objective-C Core ML implementation.
- A default-off runtime selection for exactly visual encoder level 0, block 0,
  with weight prefix `encoder.down.0.block.0`.
- The fixed single-image boundary `[B,T,H,W,C] = [1,1,256,256,128]`, F32 at the
  C/Core ML boundary and FLOAT16 for ML Program internal compute and weights.
- One Core ML graph containing group-norm plus SiLU, Conv3D 128-to-128,
  group-norm plus SiLU, Conv3D 128-to-128, and residual add.
- Preflight placement reporting, backend/fallback stats, focused tests, an
  opt-in real-model offline qualification and shadow benchmark, and operator
  documentation.
- Metal remains the default implementation and numerical oracle.

### Out

- Full DiT, text encoder, audio path, decoder, or multi-block ANE migration.
- Per-operator ANE dispatch from the general `h3_gpu_*` API.
- Bundling the MiniMax-H3 weights or generated Core ML artifacts in git.
- Executing a model whose compute plan does not include Neural Engine as a
  supported device for the candidate operation.
- Enabling the experimental backend by default or changing output quality
  presets.
- Claiming a production performance improvement from build/test success alone.

## Assumptions and Preconditions

| Claim | Command | Observed at | Observed result | Evidence source |
|---|---|---|---|---|
| The build already supports Objective-C and Apple compute frameworks. | `sed -n '1,20p' Makefile` | `2026-08-11T13:49:07Z` | Objective-C sources are compiled and Metal, MPS, and MPSGraph are linked. | `Makefile:1-17` |
| The candidate block is a stable isolated function with 128-channel level 0. | `sed -n '13,27p;286,321p;419,471p' h3_video_encoder.c` | `2026-08-11T13:49:07Z` | Six levels and two blocks exist; level 0 uses 128 channels; the block contains normalization, two convolutions, residual add, and optional shortcut. | `h3_video_encoder.c` |
| Existing MPSGraph paths use a nil execution descriptor and therefore need live placement measurement rather than an ANE assumption. | `sed -n '1538,1545p;1919,1925p;2392,2398p' h3_gpu.m` | `2026-08-11T13:49:07Z` | SDPA, Conv3D, and linear graph executions pass `executionDescriptor:nil`. | `h3_gpu.m` |
| The real 256 fixture is not installed in this checkout. | `test -f misc/fixtures/h3_real_video_encoder_256.safetensors` | `2026-08-11T13:49:07Z` | Command returned false; real parity execution is currently fixture-gated. | Working tree observation; fixture path is gitignored. |
| Production FL2VA weights are locally available for offline conversion and qualification. | `test -f MiniMax-H3/FL2VA/video_vae/source/model.safetensors && du -sh MiniMax-H3/FL2VA/video_vae/source` | `2026-08-11T13:57:16Z` | The source weights exist and occupy about 9.7 GiB. | Gitignored local model snapshot. |
| The installed SDK supports the experiment floor and placement tooling. | `xcrun --show-sdk-version && command -v xctrace` | `2026-08-11T13:57:16Z` | SDK 26.5 and `/usr/bin/xctrace` are present. | Local developer environment. |
| Conversion packages are not preinstalled. | `python3 -c 'import coremltools, numpy, safetensors'` | `2026-08-11T13:57:16Z` | Command exits 1; conversion must use an isolated explicit tool environment. | Local Python environment. |

## Architecture

The existing Metal implementation remains authoritative. A private opaque
`h3_ane` handle owns one loaded and compiled Core ML model plus placement,
fingerprint, qualification, and timing metadata. The visual encoder asks the
handle whether the exact candidate shape is supported, performs prediction into
separate output storage, applies online structural checks, and only then adopts
it. Any failure discards that storage and calls the existing `run_block` path
from the original input.

Artifact metadata contains the model variant and a deterministic SHA-256 digest
over the ordered raw bytes plus names, shapes, and dtypes of every selected
level-0/block-0 source tensor. Runtime computes the same digest from the active
weight store once during candidate initialization and caches it. A digest,
variant, or metadata mismatch prevents prediction and selects Metal.

Offline qualification emits a signed-by-content receipt sidecar next to the
compiled model. The receipt schema records its version, SHA-256 digest of every
file in the compiled-model directory in sorted relative-path order, source-
tensor fingerprint, test-vector generator/version, max-absolute error,
relative-L2 error, timestamp, and `status: passed`. Non-shadow execution hashes
the compiled directory and validates every receipt field plus the parity bounds
before loading. A missing, failed, stale, or mismatched receipt selects Metal.
Shadow mode may load without a receipt because it always adopts Metal output.

Numerical parity is an offline qualification, not an online oracle. Normal
experimental execution checks only contract version, fingerprint, exact element
count/shape/dtype, prediction status, and all-finite output. A diagnostic shadow
mode runs Core ML and Metal from the same immutable input, reports numerical
error, adopts Metal output, and is the only runtime mode that evaluates parity.

The Core ML bridge is deliberately subgraph-oriented. It does not extend every
`h3_gpu_*` operator because graph compilation and CPU/Metal/Core ML boundaries
would dominate small dispatches. Model generation is an offline developer tool:
runtime code consumes a compiled model path but does not convert safetensors.

## Interface and Configuration

- The experiment is enabled only by an explicit diagnostic environment variable
  naming a compiled Core ML model directory.
- Core ML is configured with `MLComputeUnitsCPUAndNeuralEngine`. macOS 14.4 is
  the minimum for both shadow and non-shadow Core ML execution. `MLComputePlan`
  must report Neural Engine among supported devices for **every non-constant ML
  Program operation in the candidate graph** or runtime selects Metal.
  Preferred CPU or mixed placement is allowed for measurement but is reported
  and cannot support an ANE acceleration claim.
- A diagnostic flag prints the model's compute-plan device support and preferred
  placement when available.
- Unsupported SDK/OS versions, missing models, and incompatible models produce a
  concise diagnostic and select Metal; ordinary default runs remain silent.
- Profiling output distinguishes Core ML load, input transfer, prediction,
  output transfer, fallback count/reason, and selected backend.

## Data and Artifact Model

- Core ML model packages and compiled artifacts remain local and gitignored.
- The conversion tool consumes only the selected block's weights and emits an
  ML Program with a versioned metadata contract identifying shape, dtype, block,
  weight prefix, model variant, and source-tensor fingerprint. Qualification
  adds the compiled-model receipt described above.
- Runtime validates metadata before prediction. Unknown versions or mismatched
  contracts fall back to Metal.
- Benchmark evidence is stored outside normal source artifacts unless a later
  review explicitly selects a sanitized release artifact.

## Integration

- Add Core ML to the existing framework link set and compile the bridge as
  Objective-C (`.m`) with the existing Objective-C flags, without changing the
  public `h3.h` API or sending `-std=c11` to Objective-C++.
- Integrate selection only in the visual encoder around the fixed candidate
  block.
- Preserve all existing Metal tensor ownership and submission behavior when the
  experiment is disabled or falls back.
- Core ML availability is compile-time and runtime guarded so supported Metal
  builds retain deterministic behavior.
- Offline conversion uses an explicit isolated command such as
  `uv run --with coremltools --with numpy --with safetensors` and does not add a
  Python runtime dependency to the C binary. The converter emits ML Program
  FLOAT16 weights/compute with F32 boundary features.
- The converted block must reproduce 32-group normalization with epsilon
  `1e-6`, NDHWC activations, released OIDHW Conv3D weights, two-front temporal
  zero padding, reflected one-pixel spatial padding, and residual addition. A
  converter that cannot express any semantic exactly fails instead of emitting
  an artifact.

## Testing

- Build test for the mixed C/Objective-C link path.
- Unit tests for missing model, malformed metadata, wrong FL2VA/Ref2VA or tensor
  fingerprint, unsupported shape/dtype, prediction failure, non-finite output,
  ineligible compute plan, and deterministic Metal fallback.
- A synthetic deterministic block fixture tests layout transfer and error
  reporting without private model data.
- Offline qualification generates a deterministic candidate-block input, runs
  Core ML and Metal in shadow mode, and preserves max-absolute `2e-3` and
  relative-L2 `0.02` limits. The optional end-to-end real test continues to use
  `misc/fixtures/h3_real_video_encoder_256.safetensors` when installed.
- Benchmark tooling records 20 alternating warm A/B pairs without dropping
  samples after the declared warm-up.
- Instruments evidence is required for an ANE claim; compute-plan eligibility is
  preflight evidence only.

## Risks and Mitigations

- **Core ML partitions onto CPU:** permit it only in the diagnostic experiment
  after Neural Engine eligibility is established, report it, and reject the ANE
  claim. If Neural Engine is unsupported, retain Metal without prediction.
- **Transfer cost erases compute savings:** measure transfer-inclusive phase
  time and stop the branch when the quantitative gate fails.
- **FLOAT16 changes output:** reject the artifact during offline qualification;
  normal runtime cannot infer parity without a shadow Metal execution.
- **Private fixture/model unavailable:** keep deterministic synthetic coverage;
  do not declare real parity or speed success until private evidence is run.
- **New SDK API reduces portability:** compile/runtime guard placement inspection
  and keep Core ML execution optional.
- **Fallback corrupts state:** prediction writes separate storage; Metal input is
  read-only until Core ML output has passed validation.

## Success Criteria

1. Default builds and default runtime behavior remain Metal-only.
   - **Measured by**: `make clean && make -j8 && make test && make h3_ane_tests && ./h3_ane_tests`; the focused test asserts zero Core ML load attempts without the opt-in variable.
2. Every specified Core ML load, fingerprint, compute-plan, contract, shape,
   prediction, and online structural validation
   failure reruns the unchanged Metal block without state contamination.
   - **Measured by**: `make h3_ane_tests && ./h3_ane_tests`, comparing every
     fallback output to a fresh Metal-only execution from the same input.
3. The selected FL2VA block artifact stays below max absolute error `2e-3` and
   relative L2 `0.02` before it is eligible for non-shadow execution.
   - **Measured by**: `make h3_ane_qualification && ./h3_ane_qualification --model MiniMax-H3/FL2VA/video_vae/source --coreml-model "$H3_ANE_MODEL" --output .release-loop/evidence/ane-qualification.json`; exit zero and JSON fields `max_abs < 0.002`, `relative_l2 < 0.02`, and matching fingerprints prove qualification.
4. ANE use is never claimed from configuration or compute-plan eligibility
   alone.
   - **Measured by**: reviewer verifies that an ANE result requires a retained
     Instruments trace with Neural Engine activity overlapping prediction.
5. The harness records at least 20 alternating warm A/B pairs without omitting
   post-warm-up samples and computes paired Metal-minus-Core-ML phase latency.
   - **Measured by**: `./scripts/analyze_ane_benchmark.py .release-loop/evidence/ane-ab.json`; a performance claim passes only when `n >= 20`, the 95% bootstrap confidence interval lower bound for paired Metal-minus-Core-ML time is greater than zero, and median transfer-inclusive latency improves by at least 5%.
6. Process peak-memory evidence includes Core ML allocations rather than relying
   on `h3_gpu_stats` alone.
   - **Measured by**: `/usr/bin/time -l ./h3_ane_bench --backend metal --pairs 20 --output .release-loop/evidence/ane-metal.json` and `/usr/bin/time -l ./h3_ane_bench --backend coreml --coreml-model "$H3_ANE_MODEL" --pairs 20 --output .release-loop/evidence/ane-coreml.json`; a memory claim passes only when maximum resident set size increases by no more than 5%, with both stderr summaries retained under `.release-loop/evidence/`.
7. Energy is reported independently from latency and memory.
   - **Measured by**: an Instruments Energy/Neural Engine trace over the same A/B
     workload retained under `.release-loop/evidence/`; an energy improvement is
     claimed only when the selected exported energy counter's paired median
     improves by at least 5%, with the counter name and unit recorded.
8. The experimental implementation remains isolated and removable.
   - **Measured by**: reviewer confirms no public `h3.h` change, no per-operator
     ANE dispatch, and deleting the bridge/selection branch restores the current
     visual encoder without unrelated changes.

## Open Decisions

- Planning owns the exact environment-variable names and private bridge
  function names while preserving the interface behavior above.
- Planning owns the compile-time availability guards for the fixed macOS 14.4
  experimental floor; Metal-only operation must remain available on older OSes.
- A human operator owns the final Instruments capture and any performance claim.
  This release may ship a default-off, fingerprint-bound measurement harness
  after build, fallback, and offline qualification gates pass; it must describe
  placement, latency, energy, and memory as unverified until their independent
  evidence gates pass.
