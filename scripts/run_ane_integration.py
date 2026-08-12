#!/usr/bin/env python3
"""Run the reproducible compiler-to-production-reader ANE integration gate."""

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time


SCHEMA = "h3-ane-integration/v1"
CAPTURE_LIMIT = 65536
SUMMARY_LIMIT = 16384
PREFIX = "encoder.down.0.block.0"
TENSOR_SHAPES = {
    f"{PREFIX}.norm1.weight": (128,),
    f"{PREFIX}.norm1.bias": (128,),
    f"{PREFIX}.conv1.weight": (128, 128, 3, 3, 3),
    f"{PREFIX}.conv1.bias": (128,),
    f"{PREFIX}.norm2.weight": (128,),
    f"{PREFIX}.norm2.bias": (128,),
    f"{PREFIX}.conv2.weight": (128, 128, 3, 3, 3),
    f"{PREFIX}.conv2.bias": (128,),
}
EXPECTED_INVENTORY = {
    "total": 441,
    "constant": 292,
    "nonconstant": 149,
    "neural_engine_supported": 149,
    "cpu_only": 0,
    "gpu_only": 0,
    "unknown_nonconstant": 0,
    "constant_nil_usage": 292,
}
# Closed mirror of the public h3_ane_stage/h3_ane_code taxonomy in h3_ane.h;
# stage grouping follows the production record sites in h3_ane.m.
DIAGNOSTIC_CODES = {
    "setup": {"disabled", "os_unsupported", "allocation_failed"},
    "artifact": {"compiled_model_unreadable", "compiled_model_digest_failed",
                 "source_weights_unreadable", "source_tensor_digest_failed"},
    "contract": {"metadata_missing", "metadata_mismatch",
                 "fingerprint_mismatch", "shape_mismatch", "dtype_mismatch"},
    "receipt": {"receipt_missing", "receipt_malformed",
                "receipt_digest_mismatch", "receipt_invalid"},
    "load": {"model_load_failed", "model_load_exception"},
    "compute_plan": {"plan_timeout", "plan_load_failed", "program_missing",
                     "main_missing"},
    "eligibility": {"operation_inventory_empty",
                    "operation_inventory_limit_exceeded",
                    "operation_nesting_limit_exceeded",
                    "operation_inventory_changed", "operation_usage_unknown",
                    "operation_not_neural_engine_supported", "device_unknown"},
    "input": {"input_shape_mismatch", "input_dtype_mismatch",
              "input_copy_failed"},
    "prediction": {"prediction_failed", "prediction_exception"},
    "output": {"output_shape_mismatch", "output_dtype_mismatch",
               "output_copy_failed", "output_nonfinite"},
    "parity": {"parity_metrics_nonfinite", "parity_bounds_failed"},
    "publication": {"result_write_failed", "receipt_write_failed"},
}
DEVICE_LABELS = ("cpu", "gpu", "neural-engine")

_child = None
_temporary_outputs = set()
_authority_outputs = set()
_cancelled_signal = None
_cancel_deadline = None
WORK_MARKER = ".h3-ane-integration-owned"


class StageFailure(RuntimeError):
    def __init__(self, stage, message, *, source_sha256=None, inventory=None,
                 code=None, parity=None, stages=None, artifacts=None,
                 diagnostic=None):
        super().__init__(message)
        self.stage = stage
        self.source_sha256 = source_sha256
        self.inventory = inventory
        self.code = code
        self.parity = parity
        self.stages = stages or {}
        self.artifacts = artifacts
        self.diagnostic = diagnostic


class UnsafeOutput(ValueError):
    pass


def _cancel(signum, _frame):
    global _cancelled_signal, _cancel_deadline
    _cancelled_signal = signum
    _cancel_deadline = time.monotonic() + 2.0
    if _child is not None and _child.poll() is None:
        _child.terminate()
        return
    _finish_cancellation()


def _finish_cancellation():
    for path in tuple(_temporary_outputs):
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
    cleanup_authority()
    raise SystemExit(128 + (_cancelled_signal or signal.SIGTERM))


def _drain_tail(stream, destination):
    while True:
        chunk = stream.read(8192)
        if not chunk:
            return
        destination.extend(chunk)
        if len(destination) > CAPTURE_LIMIT:
            del destination[:-CAPTURE_LIMIT]


def run_command(argv, stage, cwd=None, env=None, allow_failure=False):
    """Run one argv-only child and retain at most CAPTURE_LIMIT bytes per stream."""
    global _child
    _child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    stdout, stderr = bytearray(), bytearray()
    readers = [threading.Thread(target=_drain_tail, args=(stream, capture))
               for stream, capture in ((_child.stdout, stdout),
                                       (_child.stderr, stderr))]
    for reader in readers:
        reader.start()
    try:
        while True:
            try:
                _child.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if _cancel_deadline is not None and \
                        time.monotonic() >= _cancel_deadline:
                    _child.kill()
                    _child.wait()
                    break
    except BaseException:
        if _child.poll() is None:
            _child.terminate()
            try:
                _child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _child.kill()
                _child.wait()
        raise
    finally:
        for reader in readers:
            reader.join()
        _child.stdout.close()
        _child.stderr.close()
    returncode = _child.returncode
    _child = None
    if _cancelled_signal is not None:
        _finish_cancellation()
    stdout = bytes(stdout).decode("utf-8", "replace")
    if returncode:
        if allow_failure:
            return stdout, returncode
        raise StageFailure(stage, f"{stage} child failed",
                           code=f"child_exit_{returncode}",
                           stages={stage: returncode})
    return (stdout, 0) if allow_failure else stdout


def atomic_json(path, document):
    path = Path(path)
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    if len(encoded.encode("utf-8")) > SUMMARY_LIMIT:
        raise ValueError("integration summary exceeds size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.tmp-",
                                             dir=path.parent)
    _temporary_outputs.add(temporary)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _temporary_outputs.discard(temporary)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        _temporary_outputs.discard(temporary)
        raise


def generate_fixture(directory):
    """Generate the exact eight-tensor deterministic synthetic safetensors store."""
    import numpy as np
    from safetensors.numpy import save_file

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tensors = {}
    for index, (name, shape) in enumerate(TENSOR_SHAPES.items()):
        size = int(np.prod(shape))
        values = ((np.arange(size, dtype=np.float32) + index) % 29 - 14) / 128
        tensors[name] = values.reshape(shape)
    save_file(tensors, directory / "model.safetensors")


def _last_json(text, stage):
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise StageFailure(stage, "child did not emit a JSON object")


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value)


def _failed(mode, failure):
    diagnostic = failure.diagnostic or {
        "stage": failure.stage, "code": failure.code,
        "message": str(failure)[:160]}
    diagnostic = _bounded_mapping(diagnostic, 8)
    inventory = dict(EXPECTED_INVENTORY) \
        if failure.inventory == EXPECTED_INVENTORY else None
    parity = _bounded_parity(failure.parity)
    artifacts = failure.artifacts if isinstance(failure.artifacts, dict) and \
        set(failure.artifacts) == {"model_sha256", "source_sha256"} and \
        all(_digest(value) for value in failure.artifacts.values()) else None
    stages = {key: value for key, value in failure.stages.items()
              if key in ("conversion", "probe", "qualification") and
              isinstance(value, int) and not isinstance(value, bool)}
    return {"schema": SCHEMA, "status": "failed", "mode": mode,
            "profile": "shadow-measurement-v1" if mode == "shadow" else None,
            "authority": False if mode == "shadow" else None,
            "source_sha256": failure.source_sha256
                if _digest(failure.source_sha256) else None,
            "inventory": inventory, "diagnostic": diagnostic,
            "parity": parity, "receipt": None,
            "artifacts": artifacts, "stages": stages}


def _bounded_mapping(value, limit):
    if not isinstance(value, dict):
        return {"stage": "integration", "code": "invalid_result",
                "message": "integration result is invalid"}
    result = {}
    canonical_keys = ("stage", "code", "message", "operation",
                      "supported_devices", "preferred_device")
    for key in canonical_keys[:limit]:
        if key not in value:
            continue
        item = value[key]
        if item is None or isinstance(item, (bool, int, float)):
            result[key] = item if not isinstance(item, float) or \
                math.isfinite(item) else None
        elif isinstance(item, str):
            result[key] = item[:160]
        elif isinstance(item, list) and len(item) <= 3 and all(
                isinstance(entry, str) and len(entry) <= 32 for entry in item):
            result[key] = item
    return result


def _bounded_parity(value):
    if not isinstance(value, dict) or set(value) != {"max_abs", "relative_l2"}:
        return None
    result = {}
    for key in ("max_abs", "relative_l2"):
        metric = value[key]
        result[key] = metric if isinstance(metric, (int, float)) and \
            not isinstance(metric, bool) and math.isfinite(metric) else None
    return result


def validate_qualification_diagnostic(document):
    stage = document.get("failure_stage")
    code = document.get("failure_code")
    message = document.get("failure_reason")
    operation = document.get("failure_operation")
    devices = document.get("supported_devices")
    preferred = document.get("preferred_device")
    if stage not in DIAGNOSTIC_CODES or code not in DIAGNOSTIC_CODES[stage] or \
            not isinstance(message, str) or not message or len(message) > 159:
        raise ValueError("invalid qualifier diagnostic taxonomy")
    if operation is not None and (stage != "eligibility" or
                                  not isinstance(operation, str) or
                                  not operation or len(operation) > 95):
        raise ValueError("invalid qualifier operation context")
    if devices is not None:
        if stage != "eligibility" or not isinstance(devices, list) or \
                not devices or len(devices) > len(DEVICE_LABELS) or \
                any(device not in DEVICE_LABELS for device in devices) or \
                devices != [device for device in DEVICE_LABELS if device in devices]:
            raise ValueError("invalid qualifier device context")
    if preferred is not None and (stage != "eligibility" or
                                  preferred not in DEVICE_LABELS or
                                  not devices or preferred not in devices):
        raise ValueError("invalid qualifier preferred device")
    return {"stage": stage, "code": code, "message": message,
            "operation": operation, "supported_devices": devices,
            "preferred_device": preferred}


def publish_failure(path, document):
    try:
        atomic_json(path, document)
    except ValueError:
        atomic_json(path, {
            "schema": SCHEMA, "status": "failed", "mode": document.get("mode"),
            "profile": document.get("profile"), "authority": document.get("authority"),
            "source_sha256": None, "inventory": None,
            "diagnostic": {"stage": "integration", "code": "invalid_result",
                           "message": "integration result is invalid"},
            "parity": None, "receipt": None, "artifacts": None, "stages": {}})


def prepare_work_directory(path):
    path = Path(path)
    marker = path / WORK_MARKER
    if path.exists():
        if not path.is_dir() or not marker.is_file() or \
                marker.read_text() != SCHEMA + "\n":
            raise StageFailure("setup", "work directory is not coordinator-owned",
                               code="unsafe_work_directory")
        shutil.rmtree(path)
    path.mkdir(parents=True)
    (path / WORK_MARKER).write_text(SCHEMA + "\n")
    return path


def cleanup_authority():
    for path in tuple(_authority_outputs):
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
    _authority_outputs.clear()


def _overlaps(left, right):
    left, right = Path(left), Path(right)
    return left == right or left in right.parents or right in left.parents


def validate_paths(output, work, weights, mode):
    protected = (
        work,
        work / "visual-block.mlpackage",
        work / "visual-block.mlmodelc",
        work / "probe.json",
        work / "qualification.json",
        Path(f"{work / 'visual-block.mlmodelc'}.qualification.json"),
    )
    if any(_overlaps(output, path) for path in protected):
        raise UnsafeOutput("output path overlaps coordinator work artifacts")
    if mode in ("real", "shadow") and _overlaps(weights, work):
        raise UnsafeOutput("weights path overlaps coordinator work directory")
    if _overlaps(output, weights):
        raise UnsafeOutput("output path overlaps source weights")


def execute(args):
    repo = Path(args.repo).resolve()
    work = Path(args.work_dir).resolve()
    output = Path(args.output).resolve()
    if args.mode in ("real", "shadow") and not args.weights:
        raise StageFailure("setup", "--weights is required in real or shadow mode")
    weights = Path(args.weights).resolve() if args.weights else work / "weights"
    validate_paths(output, work, weights, args.mode)
    work = prepare_work_directory(work)
    if args.mode == "synthetic":
        generate_fixture(weights)
    package = work / "visual-block.mlpackage"
    compiled = work / "visual-block.mlmodelc"
    converter = os.environ.get(
        "H3_ANE_INTEGRATION_CONVERTER", str(repo / "scripts/convert_ane_visual_block.py"))
    probe = os.environ.get(
        "H3_ANE_INTEGRATION_PROBE", str(repo / "h3_ane_integration_probe"))
    qualifier = os.environ.get(
        "H3_ANE_INTEGRATION_QUALIFIER", str(repo / "h3_ane_qualification"))
    stages = {}
    converted = _last_json(run_command(
        [sys.executable, converter, "--weights", str(weights), "--output",
         str(package), "--compile-output", str(compiled)], "conversion", repo),
        "conversion")
    stages["conversion"] = 0
    source_sha = converted.get("source_sha256")
    if not _digest(source_sha):
        raise StageFailure("conversion", "converter emitted an invalid source digest")
    probe_output = work / "probe.json"
    _, probe_status = run_command(
        [probe, str(compiled), "--source-sha256", source_sha,
         "--output", str(probe_output)], "probe", repo, allow_failure=True)
    stages["probe"] = probe_status
    if not probe_output.exists():
        raise StageFailure("probe", "probe child failed",
                           code=f"child_exit_{probe_status}", stages=stages)
    probe_document = json.loads(probe_output.read_text())
    if probe_document.get("status") != "passed":
        diagnostic = probe_document.get("diagnostic") or {}
        raise StageFailure(diagnostic.get("stage") or "probe",
                           diagnostic.get("message") or "production probe failed",
                           code=diagnostic.get("code"), stages=stages,
                           inventory=probe_document.get("inventory"))
    inventory = probe_document.get("inventory")
    artifacts = {
        "model_sha256": probe_document.get("model_sha256"),
        "source_sha256": probe_document.get("source_sha256"),
    }
    if not _digest(artifacts["model_sha256"]) or \
            not _digest(artifacts["source_sha256"]) or \
            artifacts["source_sha256"] != source_sha:
        raise StageFailure("artifact", "integration stage digests do not match",
                           code="digest_mismatch", source_sha256=source_sha,
                           inventory=inventory, stages=stages,
                           artifacts=artifacts)
    if not isinstance(inventory, dict) or inventory != EXPECTED_INVENTORY:
        raise StageFailure("eligibility", "unexpected production inventory")
    inventory = dict(EXPECTED_INVENTORY)
    parity = receipt = None
    if args.mode in ("real", "shadow"):
        qualification_output = work / "qualification.json"
        receipt_path = Path(f"{compiled}.qualification.json")
        _authority_outputs.update((qualification_output, receipt_path))
        qualifier_command = [qualifier]
        if args.mode == "shadow":
            qualifier_command.append("--shadow-only")
        qualifier_command.extend([
            "--model", str(weights), "--coreml-model", str(compiled),
            "--output", str(qualification_output)])
        try:
            run_command(qualifier_command, "qualification", repo)
        except StageFailure:
            if not qualification_output.exists():
                raise
            failed = json.loads(qualification_output.read_text())
            try:
                diagnostic = validate_qualification_diagnostic(failed)
            except ValueError as exc:
                raise StageFailure(
                    "qualification", str(exc), code="invalid_result",
                    source_sha256=source_sha, inventory=inventory,
                    stages={**stages, "qualification": 1},
                    artifacts=artifacts) from None
            parity = {"max_abs": failed.get("max_abs"),
                      "relative_l2": failed.get("relative_l2")}
            if args.mode == "shadow":
                code = failed.get("failure_code")
                metrics_finite = all(
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value) for value in parity.values())
                code_matches_metrics = (
                    code == "parity_bounds_failed" and metrics_finite and
                    (parity["max_abs"] < 0 or parity["relative_l2"] < 0 or
                     parity["max_abs"] >= 0.25 or
                     parity["relative_l2"] >= 0.05)) or (
                    code == "parity_metrics_nonfinite" and
                    not metrics_finite)
                if failed.get("status") != "failed" or \
                        failed.get("profile") != "shadow-measurement-v1" or \
                        failed.get("authority") is not False or \
                        failed.get("bounds") != {
                            "max_abs": 0.25, "relative_l2": 0.05} or \
                        failed.get("threshold_outcome") is not False or \
                        failed.get("receipt_path") is not None or \
                        receipt_path.exists():
                    raise StageFailure(
                        "qualification",
                        "shadow failure authority contract failed",
                        code="shadow_authority_violation",
                        source_sha256=source_sha, inventory=inventory,
                        stages={**stages, "qualification": 1},
                        artifacts=artifacts)
                if diagnostic["stage"] == "parity" and not code_matches_metrics or \
                        failed.get("model_sha256") != artifacts["model_sha256"] or \
                        (failed.get("source_sha256") != source_sha and
                         diagnostic["code"] not in {
                             "source_weights_unreadable",
                             "source_tensor_digest_failed"}):
                    raise StageFailure(
                        "qualification",
                        "shadow failure diagnostic contract failed",
                        code="shadow_authority_violation",
                        source_sha256=source_sha, inventory=inventory,
                        stages={**stages, "qualification": 1},
                        artifacts=artifacts)
            raise StageFailure(
                failed.get("failure_stage") or "qualification",
                failed.get("failure_reason") or "qualification failed",
                source_sha256=source_sha, inventory=inventory,
                code=failed.get("failure_code"), parity=parity,
                stages={**stages, "qualification": 1},
                artifacts=artifacts,
                diagnostic=diagnostic if args.mode == "shadow" else None)
        stages["qualification"] = 0
        qualification = json.loads(qualification_output.read_text())
        if args.mode == "shadow":
            max_abs = qualification.get("max_abs")
            relative_l2 = qualification.get("relative_l2")
            bounded = all(
                isinstance(value, (int, float)) and not isinstance(value, bool) and
                math.isfinite(value)
                for value in (max_abs, relative_l2)) and \
                0 <= max_abs < 0.25 and 0 <= relative_l2 < 0.05
            if qualification.get("status") != "passed" or \
                    qualification.get("profile") != "shadow-measurement-v1" or \
                    qualification.get("authority") is not False or \
                    qualification.get("bounds") != {
                        "max_abs": 0.25, "relative_l2": 0.05} or \
                    qualification.get("threshold_outcome") is not True or \
                    not bounded or \
                    qualification.get("receipt_path") is not None or \
                    receipt_path.exists() or \
                    qualification.get("model_sha256") != artifacts["model_sha256"] or \
                    qualification.get("source_sha256") != source_sha:
                raise StageFailure(
                    "qualification", "shadow measurement authority contract failed",
                    code="shadow_authority_violation", source_sha256=source_sha,
                    inventory=inventory, stages=stages, artifacts=artifacts)
            parity = {"max_abs": qualification.get("max_abs"),
                      "relative_l2": qualification.get("relative_l2")}
            receipt = None
        else:
            receipt_document = json.loads(receipt_path.read_text())
            if qualification.get("status") != "passed" or \
                    receipt_document.get("status") != "passed" or \
                    not all(_digest(document.get(field)) for document in
                            (qualification, receipt_document)
                            for field in ("model_sha256", "source_sha256")) or \
                    qualification.get("model_sha256") != artifacts["model_sha256"] or \
                    receipt_document.get("model_sha256") != artifacts["model_sha256"] or \
                    qualification.get("source_sha256") != source_sha or \
                    receipt_document.get("source_sha256") != source_sha:
                raise StageFailure("artifact", "integration stage digests do not match",
                                   code="digest_mismatch", source_sha256=source_sha,
                                   inventory=inventory, stages=stages,
                                   artifacts=artifacts)
            parity = {"max_abs": qualification.get("max_abs"),
                      "relative_l2": qualification.get("relative_l2")}
            receipt = {key: receipt_document.get(key) for key in (
                "version", "model_sha256", "source_sha256", "test_vector",
                "qualified_at", "max_abs", "relative_l2", "status")}
    document = {"schema": SCHEMA, "status": "passed", "mode": args.mode,
                "profile": "shadow-measurement-v1" if args.mode == "shadow" else None,
                "authority": False if args.mode == "shadow" else None,
                "source_sha256": source_sha, "inventory": inventory,
                "diagnostic": None, "parity": parity, "receipt": receipt,
                "artifacts": artifacts, "stages": stages}
    try:
        atomic_json(output, document)
    except BaseException:
        cleanup_authority()
        raise
    _authority_outputs.clear()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("synthetic", "real", "shadow"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--weights")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGINT, _cancel)
    signal.signal(signal.SIGTERM, _cancel)
    try:
        return execute(args)
    except UnsafeOutput as exc:
        print(f"run_ane_integration.py: setup: {exc}", file=sys.stderr)
        return 2
    except StageFailure as exc:
        cleanup_authority()
        publish_failure(args.output, _failed(args.mode, exc))
        print(f"run_ane_integration.py: {exc.stage}: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        cleanup_authority()
        failure = StageFailure("integration", "integration result is invalid",
                               code="invalid_result")
        try:
            publish_failure(args.output, _failed(args.mode, failure))
        except OSError:
            pass
        print("run_ane_integration.py: integration: integration result is invalid",
              file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
