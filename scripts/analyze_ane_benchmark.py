#!/usr/bin/env python3
"""Validate and analyze paired H3 Metal/Core ML benchmark evidence."""

import argparse
import json
import math
import random
import statistics
import sys


SCHEMA = "h3-ane-benchmark/v1"
BOOTSTRAP_SEED = 0x4833414E45
BOOTSTRAP_DRAWS = 10_000
SAMPLE_FIELDS = {
    "pair", "order", "selected_backend", "metal_seconds",
    "coreml_input_seconds", "coreml_prediction_seconds",
    "coreml_output_seconds", "coreml_total_seconds", "max_abs",
    "relative_l2",
}


def _number(value, field, *, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{field} must be finite and nonnegative")
    return value


def _percentile(sorted_values, probability):
    index = int(probability * (len(sorted_values) - 1))
    return sorted_values[index]


def bootstrap_ci(values, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED):
    if not values:
        raise ValueError("cannot bootstrap an empty sample")
    rng = random.Random(seed)
    count = len(values)
    medians = [
        statistics.median(values[rng.randrange(count)] for _ in range(count))
        for _ in range(draws)
    ]
    medians.sort()
    return _percentile(medians, 0.025), _percentile(medians, 0.975)


def _paired_latencies(document):
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")
    if document.get("mode") != "ab":
        raise ValueError("mode must be ab for paired analysis")
    pairs = document.get("pairs")
    if isinstance(pairs, bool) or not isinstance(pairs, int) or pairs < 20:
        raise ValueError("at least 20 pairs are required")
    warmup = document.get("warmup")
    if isinstance(warmup, bool) or not isinstance(warmup, int) or warmup < 0:
        raise ValueError("warmup must be a nonnegative integer")
    if not isinstance(document.get("placement_summary"), str):
        raise ValueError("placement_summary must be a string")
    _number(document.get("peak_rss_bytes"), "peak_rss_bytes")
    samples = document.get("samples")
    if not isinstance(samples, list) or len(samples) != pairs * 2:
        raise ValueError("sample set must contain two complete samples per pair")

    result = []
    for pair in range(pairs):
        expected_order = "AB" if pair % 2 == 0 else "BA"
        expected_backends = ("metal", "coreml") if expected_order == "AB" \
            else ("coreml", "metal")
        current = samples[pair * 2:pair * 2 + 2]
        observed = []
        for offset, sample in enumerate(current):
            if not isinstance(sample, dict) or set(sample) != SAMPLE_FIELDS:
                raise ValueError("every sample must contain the exact benchmark schema")
            if sample["pair"] != pair:
                raise ValueError("samples must be complete and ordered by pair")
            if sample["order"] != expected_order:
                raise ValueError("pair order must alternate AB then BA")
            backend = sample["selected_backend"]
            if backend != expected_backends[offset]:
                raise ValueError("samples must follow the alternating pair order")
            observed.append(sample)
        by_backend = {sample["selected_backend"]: sample for sample in observed}
        metal = by_backend["metal"]
        coreml = by_backend["coreml"]
        metal_seconds = _number(metal["metal_seconds"], "metal_seconds")
        for field in SAMPLE_FIELDS - {"pair", "order", "selected_backend", "metal_seconds"}:
            if metal[field] is not None:
                raise ValueError(f"Metal sample {field} must be null")
        for field in ("coreml_input_seconds", "coreml_prediction_seconds",
                      "coreml_output_seconds", "coreml_total_seconds",
                      "max_abs", "relative_l2"):
            _number(coreml[field], field)
        if coreml["metal_seconds"] is not None:
            raise ValueError("Core ML sample metal_seconds must be null")
        phase_sum = (coreml["coreml_input_seconds"] +
                     coreml["coreml_prediction_seconds"] +
                     coreml["coreml_output_seconds"])
        if not math.isclose(phase_sum, coreml["coreml_total_seconds"],
                            rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("Core ML phase times do not sum to coreml_total_seconds")
        result.append((metal_seconds, float(coreml["coreml_total_seconds"])))
    return result


def analyze(document):
    pairs = _paired_latencies(document)
    metal = [item[0] for item in pairs]
    coreml = [item[1] for item in pairs]
    differences = [left - right for left, right in pairs]
    median_difference = statistics.median(differences)
    median_metal = statistics.median(metal)
    median_coreml = statistics.median(coreml)
    improvement = median_difference / median_metal if median_metal else 0.0
    lower, upper = bootstrap_ci(differences)
    return {
        "schema": "h3-ane-benchmark-analysis/v1",
        "n": len(pairs),
        "median_metal_seconds": median_metal,
        "median_coreml_seconds": median_coreml,
        "median_metal_minus_coreml_seconds": median_difference,
        "ci95_lower_seconds": lower,
        "ci95_upper_seconds": upper,
        "median_improvement_fraction": improvement,
        "claim_passed": lower > 0.0 and improvement >= 0.05,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="complete h3-ane-benchmark/v1 JSON")
    args = parser.parse_args(argv)
    try:
        with open(args.input, encoding="utf-8") as stream:
            result = analyze(json.load(stream))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"analyze_ane_benchmark.py: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["claim_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
