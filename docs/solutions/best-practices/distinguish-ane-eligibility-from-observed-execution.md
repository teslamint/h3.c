---
module: Core ML and ANE acceleration
date: 2026-08-12
problem_type: best_practice
component: acceleration_evidence_workflow
severity: high
applies_when:
  - "Interpreting MLComputePlan supported-device or preferred-device diagnostics"
  - "Claiming Apple Neural Engine placement or acceleration"
  - "Writing operator-run qualification, benchmark, or Instruments evidence"
related_components:
  - coreml_bridge
  - benchmark_tooling
  - operator_documentation
tags:
  - ane
  - core-ml
  - compute-plan
  - evidence-boundaries
  - operator-commands
---

# Distinguish ANE eligibility from observed execution

## Context

The ANE release loop delivered a default-off Core ML measurement harness, not
proof of ANE acceleration. `MLComputePlan` exposed supported and preferred
devices, but real qualification failed closed with `ANE backend is unavailable`
and produced no passing receipt.

Running the declared operator commands verbatim also exposed two release gaps:
the Python entry points lacked executable bits, and the benchmark loaded BF16
weights although the released visual-encoder checkpoint stores F32.

## Guidance

- Treat compute-plan support and preference as eligibility diagnostics only.
  Never label them as observed execution.
- Run documented commands verbatim from a clean checkout against real artifacts.
  Help output, synthetic fixtures, and equivalent substitute invocations do not
  prove the published workflow.
- Keep the evidence ladder separate:
  1. Conversion and compilation prove artifact readiness.
  2. A digest-bound qualification receipt proves numerical parity.
  3. Instruments proves Neural Engine placement during the measured prediction.
  4. Independent quantitative gates support latency, memory, and energy claims.
- Fail closed when any required receipt, trace, sample set, or metric is absent.

## Why This Matters

Configuration intent is easy to mistake for hardware behavior. A model may list
Neural Engine support yet execute elsewhere, while a benchmark may compile and
pass fixture tests but fail immediately with production weights. Exact commands
and independent evidence gates prevent readiness signals from becoming
unsupported performance claims.

## When to Apply

Use this approach for hardware-accelerated or heterogeneous compute paths,
experimental backends, model conversion and qualification tools, executable
operator workflows, and latency, memory, energy, or placement claims.

## Examples

- Report `compute-plan-preference:cpu+neural-engine`, not “observed ANE
  execution.”
- Executing `./scripts/analyze_ane_benchmark.py ...` revealed that the script
  was not executable; the published command itself became a release test.
- Running the documented benchmark with released weights exposed BF16 loaders;
  switching to F32 matched the checkpoint and allowed 20 Metal samples to run.
- An acceleration claim requires all applicable evidence: parity below the
  declared error bounds, retained overlapping Neural Engine activity, at least
  20 alternating samples with a positive confidence-bound improvement, and
  independently qualified memory and energy results.

## Prevention

Before merging an acceleration harness, run every documented command exactly,
exercise at least one production-format artifact, and make the reviewer label
each result as eligibility, qualification, observed placement, or performance.
