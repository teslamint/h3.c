import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import os
import signal
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTensor:
    def __init__(self, shape, values):
        self.shape = shape
        self.values = values


class Reshapable:
    def __init__(self, values):
        self.values = values

    def reshape(self, shape):
        return (tuple(shape), self.values)


class PlaneWeights:
    def __init__(self):
        self.selection = None

    def __getitem__(self, selection):
        self.selection = selection
        return ("selected-plane", selection)


def complete_benchmark(metal=1.0, coreml=0.8, pairs=20):
    samples = []
    for pair in range(pairs):
        order = "AB" if pair % 2 == 0 else "BA"
        backends = ("metal", "coreml") if order == "AB" else ("coreml", "metal")
        for backend in backends:
            samples.append({
                "pair": pair,
                "order": order,
                "selected_backend": backend,
                "metal_seconds": metal if backend == "metal" else None,
                "coreml_input_seconds": 0.05 if backend == "coreml" else None,
                "coreml_prediction_seconds": coreml - 0.1 if backend == "coreml" else None,
                "coreml_output_seconds": 0.05 if backend == "coreml" else None,
                "coreml_total_seconds": coreml if backend == "coreml" else None,
                "max_abs": 0.001 if backend == "coreml" else None,
                "relative_l2": 0.01 if backend == "coreml" else None,
            })
    return {
        "schema": "h3-ane-benchmark/v1",
        "mode": "ab",
        "warmup": 2,
        "pairs": pairs,
        "placement_summary": "synthetic-neural-engine",
        "samples": samples,
        "peak_rss_bytes": 123456,
    }


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.converter = load_script("convert_ane_visual_block.py")

    def tiny_weights(self):
        prefix = self.converter.WEIGHT_PREFIX
        return {
            f"{prefix}.norm1.weight": FakeTensor((128,), [1.0] * 128),
            f"{prefix}.norm1.bias": FakeTensor((128,), [0.0] * 128),
            f"{prefix}.conv1.weight": FakeTensor((128, 128, 3, 3, 3), [1.0]),
            f"{prefix}.conv1.bias": FakeTensor((128,), [0.0] * 128),
            f"{prefix}.norm2.weight": FakeTensor((128,), [1.0] * 128),
            f"{prefix}.norm2.bias": FakeTensor((128,), [0.0] * 128),
            f"{prefix}.conv2.weight": FakeTensor((128, 128, 3, 3, 3), [1.0]),
            f"{prefix}.conv2.bias": FakeTensor((128,), [0.0] * 128),
        }

    def test_selects_exact_fixed_block_and_preserves_oid_hw(self):
        weights = self.tiny_weights()
        selected = self.converter.select_block_tensors(weights)
        self.assertEqual(list(selected), sorted(weights))
        self.assertEqual(selected[f"{self.converter.WEIGHT_PREFIX}.conv1.weight"].shape,
                         (128, 128, 3, 3, 3))
        self.assertIs(selected[f"{self.converter.WEIGHT_PREFIX}.conv1.weight"],
                      weights[f"{self.converter.WEIGHT_PREFIX}.conv1.weight"])

    def test_rejects_missing_or_wrong_shape(self):
        weights = self.tiny_weights()
        del weights[f"{self.converter.WEIGHT_PREFIX}.conv2.bias"]
        with self.assertRaisesRegex(ValueError, "absent"):
            self.converter.select_block_tensors(weights)
        weights = self.tiny_weights()
        weights[f"{self.converter.WEIGHT_PREFIX}.conv1.weight"].shape = (128, 128, 1, 3, 3)
        with self.assertRaisesRegex(ValueError, "shape"):
            self.converter.select_block_tensors(weights)

    def test_padding_is_two_front_zero_then_spatial_reflect(self):
        source = [[[[[1.0, 2.0], [3.0, 4.0]]]]]
        padded = self.converter.pad_ncdhw_fixture(source)
        self.assertEqual(len(padded[0][0]), 3)
        self.assertEqual(padded[0][0][0], [[0.0] * 4 for _ in range(4)])
        self.assertEqual(padded[0][0][1], [[0.0] * 4 for _ in range(4)])
        self.assertEqual(padded[0][0][2], [
            [4.0, 3.0, 4.0, 3.0],
            [2.0, 1.0, 2.0, 1.0],
            [4.0, 3.0, 4.0, 3.0],
            [2.0, 1.0, 2.0, 1.0],
        ])

    def test_contract_metadata_pins_layout_norm_and_padding(self):
        metadata = self.converter.contract_metadata("a" * 64)
        self.assertEqual(metadata["version"], "1")
        self.assertEqual(metadata["variant"], "FL2VA")
        self.assertEqual(metadata["shape"], "1,1,256,256,128")
        self.assertEqual(metadata["source_sha256"], "a" * 64)
        self.assertEqual(metadata["h3_ane_boundary_layout"], "NDHWC")
        self.assertEqual(metadata["h3_ane_weight_layout"], "OIDHW")
        self.assertEqual(metadata["h3_ane_group_count"], "32")
        self.assertEqual(metadata["h3_ane_epsilon"], "1e-6")
        self.assertEqual(metadata["h3_ane_temporal_padding"], "front=2,back=0,mode=constant")
        self.assertEqual(metadata["h3_ane_spatial_padding"], "1,1,1,1,mode=reflect")

    def test_failed_publish_preserves_prior_package(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "model.mlpackage"
            destination.mkdir()
            (destination / "old").write_text("authoritative")

            class Model:
                user_defined_metadata = {}
                def save(self, path):
                    Path(path).mkdir()
                    (Path(path) / "new").write_text("candidate")

            original = self.converter._publish_directory
            self.converter._publish_directory = lambda *_: (_ for _ in ()).throw(
                OSError("injected publish failure"))
            try:
                with self.assertRaisesRegex(OSError, "publish failure"):
                    self.converter.atomic_save(Model(), destination, {})
            finally:
                self.converter._publish_directory = original
            self.assertEqual((destination / "old").read_text(), "authoritative")
            self.assertFalse(list(Path(root).glob(".model.mlpackage.tmp-*")))

    def test_compile_owns_temp_and_publishes_only_complete_model(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            package = root / "model.mlpackage"
            package.mkdir()
            destination = root / "model.mlmodelc"

            def runner(command, check):
                self.assertEqual(command[:3], ["xcrun", "coremlcompiler", "compile"])
                output_root = Path(command[4])
                compiled = output_root / "model.mlmodelc"
                compiled.mkdir(parents=True)
                (compiled / "complete").write_text("yes")

            self.converter.compile_package(package, destination, runner=runner)
            self.assertEqual((destination / "complete").read_text(), "yes")
            self.assertFalse(list(root.glob(".model.mlmodelc.compile-*")))

    def test_group_norm_uses_consecutive_four_channel_native_groups_then_affine(self):
        class Recorder:
            def __init__(self):
                self.slices = []
                self.norms = []
                self.concatenations = []
                self.multiplications = []
                self.additions = []

            def slice_by_index(self, **kwargs):
                self.slices.append(kwargs)
                return f"slice-{len(self.slices) - 1}"

            def layer_norm(self, **kwargs):
                self.norms.append(kwargs)
                return f"norm-{len(self.norms) - 1}"

            def concat(self, **kwargs):
                self.concatenations.append(kwargs)
                return "concatenated"

            def mul(self, **kwargs):
                self.multiplications.append(kwargs)
                return "scaled"

            def add(self, **kwargs):
                self.additions.append(kwargs)
                return "affine"

        recorder = Recorder()
        scale = Reshapable(list(range(1, 9)))
        bias = Reshapable(list(range(-4, 4)))
        result = self.converter._group_norm(
            recorder, "nhwc", scale, bias, "norm", channels=8, groups=2,
            height=2, width=3)

        self.assertEqual(result, "affine")
        self.assertEqual(
            [(call["begin"], call["end"]) for call in recorder.slices],
            [([0, 0, 0, 0], [1, 2, 3, 4]),
             ([0, 0, 0, 4], [1, 2, 3, 8])])
        self.assertEqual([call["axes"] for call in recorder.norms],
                         [[1, 2, 3], [1, 2, 3]])
        self.assertEqual([call["epsilon"] for call in recorder.norms],
                         [1e-6, 1e-6])
        self.assertEqual(recorder.concatenations[0]["values"],
                         ["norm-0", "norm-1"])
        self.assertEqual(recorder.concatenations[0]["axis"], 3)
        self.assertEqual(recorder.multiplications[0]["y"],
                         ((1, 1, 1, 8), list(range(1, 9))))
        self.assertEqual(recorder.additions[0]["y"],
                         ((1, 1, 1, 8), list(range(-4, 4))))

    def test_conv2d_uses_only_oid_hw_plane_two_and_reflected_spatial_padding(self):
        class Recorder:
            def __init__(self):
                self.transposes = []
                self.pads = []
                self.convolutions = []

            def transpose(self, **kwargs):
                self.transposes.append(kwargs)
                return "nchw" if len(self.transposes) == 1 else "nhwc"

            def pad(self, **kwargs):
                self.pads.append(kwargs)
                return "reflected"

            def conv(self, **kwargs):
                self.convolutions.append(kwargs)
                return "convolved"

        recorder = Recorder()
        weights = PlaneWeights()
        result = self.converter._padded_conv(
            recorder, "nhwc", weights, [1.0, 2.0],
            "conv")

        self.assertEqual(result, "nhwc")
        self.assertEqual([call["perm"] for call in recorder.transposes],
                         [[0, 3, 1, 2], [0, 2, 3, 1]])
        self.assertEqual(recorder.pads[0]["pad"],
                         [0, 0, 0, 0, 1, 1, 1, 1])
        self.assertEqual(recorder.pads[0]["mode"], "reflect")
        self.assertEqual(weights.selection,
                         (slice(None), slice(None), 2, slice(None), slice(None)))
        self.assertEqual(recorder.convolutions[0]["weight"][0], "selected-plane")
        self.assertEqual(recorder.convolutions[0]["pad_type"], "valid")

        corner_source = [[[[[1.0, 2.0], [3.0, 4.0]]]]]
        self.assertEqual(self.converter.pad_ncdhw_fixture(corner_source)[0][0][2][0][0],
                         4.0)

    def test_fixed_graph_squeezes_and_restores_depth_with_silu_residual_order(self):
        class Recorder:
            def __init__(self):
                self.calls = []

            def __getattr__(self, operation):
                def record(**kwargs):
                    self.calls.append((operation, kwargs))
                    return kwargs.get("name", operation)
                return record

        recorder = Recorder()
        weights = {
            f"{self.converter.WEIGHT_PREFIX}.norm1.weight": Reshapable([1.0] * 8),
            f"{self.converter.WEIGHT_PREFIX}.norm1.bias": Reshapable([0.0] * 8),
            f"{self.converter.WEIGHT_PREFIX}.conv1.weight": PlaneWeights(),
            f"{self.converter.WEIGHT_PREFIX}.conv1.bias": [0.0] * 8,
            f"{self.converter.WEIGHT_PREFIX}.norm2.weight": Reshapable([1.0] * 8),
            f"{self.converter.WEIGHT_PREFIX}.norm2.bias": Reshapable([0.0] * 8),
            f"{self.converter.WEIGHT_PREFIX}.conv2.weight": PlaneWeights(),
            f"{self.converter.WEIGHT_PREFIX}.conv2.bias": [0.0] * 8,
        }
        result = self.converter._fixed_graph(
            recorder, "input5d", weights, (1, 1, 2, 3, 8), groups=2)

        operations = [operation for operation, _ in recorder.calls]
        self.assertEqual(operations[0], "squeeze")
        self.assertEqual(recorder.calls[0][1]["axes"], [1])
        self.assertEqual(operations.count("layer_norm"), 4)
        self.assertEqual(operations.count("conv"), 2)
        self.assertEqual(operations.count("silu"), 2)
        residual_index = next(i for i, call in enumerate(recorder.calls)
                              if call[1].get("name") == "residual")
        restore_index = next(i for i, call in enumerate(recorder.calls)
                             if call[1].get("name") == "restore_depth")
        self.assertLess(residual_index, restore_index)
        self.assertEqual(recorder.calls[residual_index][1]["x"], "remove_depth")
        self.assertEqual(recorder.calls[restore_index][1]["axes"], [1])
        self.assertEqual(result, "restore_depth")

    def test_boundary_shape_is_exact_f32_five_dimensional_contract(self):
        self.assertEqual(self.converter.BOUNDARY_SHAPE,
                         (1, 1, 256, 256, 128))
        self.assertEqual(self.converter.contract_metadata("a" * 64)["boundary_dtype"],
                         "F32")

    def test_compiled_schema_requires_one_f32_five_dimensional_input_and_output(self):
        class MultiArray:
            def __init__(self, shape, data_type):
                self.shape = shape
                self.dataType = data_type

        class Type:
            def __init__(self, shape, data_type):
                self.multiArrayType = MultiArray(shape, data_type)

            def WhichOneof(self, _):
                return "multiArrayType"

        class Feature:
            def __init__(self, shape, data_type):
                self.type = Type(shape, data_type)

        class Description:
            input = [Feature([1, 1, 256, 256, 128], 65568)]
            output = [Feature([1, 1, 256, 256, 128], 65568)]

        class Spec:
            description = Description()

        self.converter._validate_model_schema(
            Spec(), (1, 1, 256, 256, 128), 65568)
        Description.output = [Feature([1, 256, 256, 128], 65568)]
        with self.assertRaisesRegex(ValueError, "shape"):
            self.converter._validate_model_schema(
                Spec(), (1, 1, 256, 256, 128), 65568)


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = load_script("analyze_ane_benchmark.py")

    def test_accepts_complete_alternating_pairs_and_positive_sign(self):
        result = self.analyzer.analyze(complete_benchmark())
        self.assertEqual(result["n"], 20)
        self.assertAlmostEqual(result["median_metal_minus_coreml_seconds"], 0.2)
        self.assertGreater(result["ci95_lower_seconds"], 0.0)
        self.assertAlmostEqual(result["median_improvement_fraction"], 0.2)
        self.assertTrue(result["claim_passed"])

    def test_bootstrap_is_deterministic(self):
        data = complete_benchmark()
        first = self.analyzer.analyze(data)
        second = self.analyzer.analyze(data)
        self.assertEqual(first["ci95_lower_seconds"], second["ci95_lower_seconds"])
        self.assertEqual(first["ci95_upper_seconds"], second["ci95_upper_seconds"])

    def test_rejects_fewer_than_twenty_incomplete_and_nonalternating(self):
        with self.assertRaisesRegex(ValueError, "at least 20"):
            self.analyzer.analyze(complete_benchmark(pairs=19))
        data = complete_benchmark()
        data["samples"].pop()
        with self.assertRaisesRegex(ValueError, "complete"):
            self.analyzer.analyze(data)
        data = complete_benchmark()
        data["samples"][2]["order"] = "AB"
        with self.assertRaisesRegex(ValueError, "alternat"):
            self.analyzer.analyze(data)

    def test_requires_positive_ci_and_five_percent_median(self):
        slow = self.analyzer.analyze(complete_benchmark(metal=1.0, coreml=1.1))
        self.assertFalse(slow["claim_passed"])
        small = self.analyzer.analyze(complete_benchmark(metal=1.0, coreml=0.96))
        self.assertFalse(small["claim_passed"])

    def test_cli_prints_result_json(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bench.json"
            path.write_text(json.dumps(complete_benchmark()))
            result = subprocess.run(
                ["python3", str(ROOT / "scripts/analyze_ane_benchmark.py"), str(path)],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["claim_passed"])


class IntegrationCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = load_script("run_ane_integration.py")

    def write_tool(self, path, body):
        path.write_text("#!/usr/bin/env python3\n" + body)
        path.chmod(0o755)

    def fixture_tools(self, root, inventory=None):
        converter = root / "converter.py"
        probe = root / "probe.py"
        qualifier = root / "qualifier.py"
        inventory = inventory or {
            "total": 441, "constant": 292, "nonconstant": 149,
            "neural_engine_supported": 149, "cpu_only": 0, "gpu_only": 0,
            "unknown_nonconstant": 0, "constant_nil_usage": 292,
        }
        self.write_tool(converter, """
import json, pathlib, sys
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).mkdir()
pathlib.Path(sys.argv[sys.argv.index('--compile-output') + 1]).mkdir()
print(json.dumps({'source_sha256': 'a' * 64}))
""")
        self.write_tool(probe, f"""
import json, pathlib, sys
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps({{
    'status': 'passed', 'model_sha256': 'b' * 64,
    'source_sha256': 'a' * 64,
    'inventory': {inventory!r}, 'diagnostic': None}}))
""")
        self.write_tool(qualifier, """
import json, pathlib, sys
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
document = {'status': 'passed', 'model_sha256': 'b' * 64,
            'source_sha256': 'a' * 64, 'max_abs': 0.001, 'relative_l2': 0.01}
output.write_text(json.dumps(document))
receipt = dict(document, version=1, test_vector='xorshift32-v1',
               qualified_at='2026-08-12T00:00:00Z')
pathlib.Path(str(model) + '.qualification.json').write_text(json.dumps(receipt))
""")
        return converter, probe, qualifier

    def run_real(self, root, tools):
        converter, probe, qualifier = tools
        output = root / "summary.json"
        env = os.environ.copy()
        env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                    "H3_ANE_INTEGRATION_PROBE": str(probe),
                    "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
        weights = root / "weights"; weights.mkdir(exist_ok=True)
        command = [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                   "real", "--repo", str(ROOT), "--work-dir", str(root / "work"),
                   "--output", str(output), "--weights", str(weights)]
        return subprocess.run(command, env=env, text=True, capture_output=True,
                              check=False), output, env, command

    def test_shadow_success_is_non_authorizing_and_cleans_stale_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter, probe, qualifier = self.fixture_tools(root)
            self.write_tool(qualifier, """
import json, pathlib, sys
assert '--shadow-only' in sys.argv
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
receipt = pathlib.Path(str(model) + '.qualification.json')
receipt.write_text(json.dumps({
    'version': 1, 'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'test_vector': 'xorshift32-v1', 'qualified_at': '2026-08-12T00:00:00Z',
    'max_abs': 0.001, 'relative_l2': 0.01, 'status': 'passed'}))
receipt.unlink(missing_ok=True)
output.write_text(json.dumps({
    'schema': 'h3-ane-qualification/v1', 'status': 'passed',
    'profile': 'shadow-measurement-v1', 'authority': False,
    'measurement_started': True, 'authority_state': 'invalidated',
    'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'max_abs': 0.19, 'relative_l2': 0.038,
    'bounds': {'max_abs': 0.25, 'relative_l2': 0.05},
    'threshold_outcome': True,
    'receipt_path': None}))
""")
            output = root / "summary.json"
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                        "H3_ANE_INTEGRATION_PROBE": str(probe),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
            weights = root / "weights"; weights.mkdir()
            command = [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                       "shadow", "--repo", str(ROOT), "--work-dir", str(root / "work"),
                       "--output", str(output), "--weights", str(weights)]
            result = subprocess.run(command, env=env, text=True,
                                    capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(output.read_text())
            self.assertEqual(document["status"], "passed")
            self.assertEqual(document["mode"], "shadow")
            self.assertEqual(document["profile"], "shadow-measurement-v1")
            self.assertFalse(document["authority"])
            self.assertEqual(document["parity"], {"max_abs": 0.19,
                                                   "relative_l2": 0.038})
            self.assertIsNone(document["receipt"])
            self.assertFalse(Path(
                f"{root / 'work' / 'visual-block.mlmodelc'}.qualification.json").exists())

    def test_shadow_summary_publication_failure_cleans_measurement_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter, probe, qualifier = self.fixture_tools(root)
            self.write_tool(qualifier, """
import json, pathlib, sys
assert '--shadow-only' in sys.argv
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
receipt = pathlib.Path(str(model) + '.qualification.json')
receipt.write_text(json.dumps({
    'version': 1, 'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'test_vector': 'xorshift32-v1', 'qualified_at': '2026-08-12T00:00:00Z',
    'max_abs': 0.001, 'relative_l2': 0.01, 'status': 'passed'}))
receipt.unlink()
output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
output.write_text(json.dumps({
    'schema': 'h3-ane-qualification/v1', 'status': 'passed',
    'profile': 'shadow-measurement-v1', 'authority': False,
    'measurement_started': True, 'authority_state': 'invalidated',
    'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'max_abs': 0.19, 'relative_l2': 0.038,
    'bounds': {'max_abs': 0.25, 'relative_l2': 0.05},
    'threshold_outcome': True,
    'receipt_path': None}))
""")
            output = root / "output-directory"; output.mkdir()
            work = root / "work"
            weights = root / "weights"; weights.mkdir()
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                        "H3_ANE_INTEGRATION_PROBE": str(probe),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "shadow", "--repo", str(ROOT), "--work-dir", str(work),
                 "--output", str(output), "--weights", str(weights)],
                env=env, text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((work / "qualification.json").exists())
            self.assertFalse(Path(
                f"{work / 'visual-block.mlmodelc'}.qualification.json").exists())

    def test_shadow_rejects_out_of_bounds_passing_qualifier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter, probe, qualifier = self.fixture_tools(root)
            self.write_tool(qualifier, """
import json, pathlib, sys
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
pathlib.Path(str(model) + '.qualification.json').write_text(json.dumps({
    'version': 1, 'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'test_vector': 'xorshift32-v1', 'qualified_at': '2026-08-12T00:00:00Z',
    'max_abs': 0.001, 'relative_l2': 0.01, 'status': 'passed'}))
output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
output.write_text(json.dumps({
    'schema': 'h3-ane-qualification/v1', 'status': 'passed',
    'profile': 'shadow-measurement-v1', 'authority': False,
    'measurement_started': True, 'authority_state': 'invalidated',
    'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'max_abs': 0.25, 'relative_l2': 0.05,
    'bounds': {'max_abs': 0.25, 'relative_l2': 0.05},
    'threshold_outcome': True, 'receipt_path': None}))
""")
            output = root / "summary.json"
            weights = root / "weights"; weights.mkdir()
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                        "H3_ANE_INTEGRATION_PROBE": str(probe),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "shadow", "--repo", str(ROOT),
                 "--work-dir", str(root / "work"), "--output", str(output),
                 "--weights", str(weights)], env=env, text=True,
                capture_output=True, check=False)
            self.assertEqual(result.returncode, 1)
            document = json.loads(output.read_text())
            self.assertEqual(document["diagnostic"]["code"],
                             "shadow_authority_violation")
            self.assertIsNone(document["receipt"])
            self.assertFalse(Path(
                f"{root / 'work' / 'visual-block.mlmodelc'}.qualification.json").exists())

    def test_shadow_failure_preserves_diagnostic_and_removes_authority(self):
        cases = (("parity_bounds_failed", 0.25, 0.04),
                 ("parity_metrics_nonfinite", None, 0.04))
        for code, max_abs, relative_l2 in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                converter, probe, qualifier = self.fixture_tools(root)
                self.write_tool(qualifier, f"""
import json, pathlib, sys
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
receipt = pathlib.Path(str(model) + '.qualification.json')
receipt.write_text(json.dumps({{
    'version': 1, 'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'test_vector': 'xorshift32-v1', 'qualified_at': '2026-08-12T00:00:00Z',
    'max_abs': 0.001, 'relative_l2': 0.01, 'status': 'passed'}}))
receipt.unlink()
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps({{
    'schema': 'h3-ane-qualification/v1', 'status': 'failed',
    'profile': 'shadow-measurement-v1', 'authority': False,
    'measurement_started': True, 'authority_state': 'invalidated',
    'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'max_abs': {max_abs!r}, 'relative_l2': {relative_l2!r},
    'bounds': {{'max_abs': 0.25, 'relative_l2': 0.05}},
    'threshold_outcome': False, 'receipt_path': None,
    'failure_stage': 'parity', 'failure_code': {code!r},
    'failure_reason': 'parity qualification failed',
    'failure_operation': None, 'supported_devices': None,
    'preferred_device': None, 'observed_count': None, 'limit': None}}))
raise SystemExit(1)
""")
                output = root / "summary.json"
                weights = root / "weights"; weights.mkdir()
                env = os.environ.copy()
                env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                            "H3_ANE_INTEGRATION_PROBE": str(probe),
                            "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                     "shadow", "--repo", str(ROOT),
                     "--work-dir", str(root / "work"), "--output", str(output),
                     "--weights", str(weights)], env=env, text=True,
                    capture_output=True, check=False)
                self.assertEqual(result.returncode, 1, result.stderr)
                document = json.loads(output.read_text())
                self.assertEqual(document["diagnostic"], {
                    "stage": "parity", "code": code,
                    "message": "parity qualification failed",
                    "operation": None, "supported_devices": None,
                    "preferred_device": None, "observed_count": None,
                    "limit": None})
                self.assertEqual(document["parity"], {
                    "max_abs": max_abs, "relative_l2": relative_l2})
                self.assertIsNone(document["receipt"])
                self.assertFalse(Path(
                    f"{root / 'work' / 'visual-block.mlmodelc'}.qualification.json").exists())

    def test_qualifier_diagnostic_taxonomy_and_context_are_closed(self):
        for stage, codes in self.coordinator.DIAGNOSTIC_CODES.items():
            for code in codes:
                with self.subTest(stage=stage, code=code):
                    document = {
                        "failure_stage": stage, "failure_code": code,
                        "failure_reason": "bounded diagnostic",
                        "failure_operation": "op" if stage == "eligibility" else None,
                        "supported_devices": ["cpu", "neural-engine"]
                            if stage == "eligibility" else None,
                        "preferred_device": "neural-engine"
                            if stage == "eligibility" else None,
                    }
                    if stage == "compute_plan" and code in {
                            "operation_inventory_empty",
                            "operation_inventory_limit_exceeded",
                            "operation_nesting_limit_exceeded",
                            "operation_inventory_changed"}:
                        document.update(observed_count=1, limit=1)
                    diagnostic = self.coordinator.validate_qualification_diagnostic(
                        document)
                    self.assertEqual(diagnostic["stage"], stage)
                    self.assertEqual(diagnostic["code"], code)
        invalid = {
            "failure_stage": "artifact", "failure_code": "parity_bounds_failed",
            "failure_reason": "mismatch", "failure_operation": None,
            "supported_devices": None, "preferred_device": None}
        with self.assertRaisesRegex(ValueError, "taxonomy"):
            self.coordinator.validate_qualification_diagnostic(invalid)
        for field, value in (("failure_operation", "fabricated-op"),
                             ("supported_devices", ["tpu"]),
                             ("preferred_device", "tpu")):
            document = dict(invalid, failure_stage="parity",
                            failure_code="parity_bounds_failed")
            document[field] = value
            with self.assertRaises(ValueError):
                self.coordinator.validate_qualification_diagnostic(document)
        production = (ROOT / "h3_ane.m").read_text()
        self.assertIn("H3_ANE_STAGE_OUTPUT, H3_ANE_CODE_ALLOCATION_FAILED",
                      production)
        output_allocation = {
            "failure_stage": "output", "failure_code": "allocation_failed",
            "failure_reason": "output allocation failed",
            "failure_operation": None, "supported_devices": None,
            "preferred_device": None, "observed_count": None, "limit": None}
        self.assertEqual(
            self.coordinator.validate_qualification_diagnostic(output_allocation)[
                "code"], "allocation_failed")
        fabricated = dict(output_allocation, failure_stage="eligibility",
                          failure_code="operation_inventory_empty")
        with self.assertRaises(ValueError):
            self.coordinator.validate_qualification_diagnostic(fabricated)
        missing_operation = dict(output_allocation, failure_stage="eligibility",
                                 failure_code="device_unknown")
        with self.assertRaisesRegex(ValueError, "operation"):
            self.coordinator.validate_qualification_diagnostic(missing_operation)
        missing_count = dict(output_allocation, failure_stage="compute_plan",
                             failure_code="operation_inventory_changed")
        with self.assertRaisesRegex(ValueError, "count"):
            self.coordinator.validate_qualification_diagnostic(missing_count)

    def test_shadow_propagates_nonparity_qualifier_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter, probe, qualifier = self.fixture_tools(root)
            self.write_tool(qualifier, """
import json, pathlib, sys
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
receipt = pathlib.Path(str(model) + '.qualification.json')
receipt.write_text(json.dumps({
    'version': 1, 'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'test_vector': 'xorshift32-v1', 'qualified_at': '2026-08-12T00:00:00Z',
    'max_abs': 0.001, 'relative_l2': 0.01, 'status': 'passed'}))
receipt.unlink()
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps({
    'schema': 'h3-ane-qualification/v1', 'status': 'failed',
    'profile': 'shadow-measurement-v1', 'authority': False,
    'measurement_started': True, 'authority_state': 'invalidated',
    'model_sha256': 'b' * 64, 'source_sha256': '',
    'max_abs': 0.0, 'relative_l2': 0.0,
    'bounds': {'max_abs': 0.25, 'relative_l2': 0.05},
    'threshold_outcome': False, 'receipt_path': None,
    'failure_stage': 'artifact',
    'failure_code': 'source_weights_unreadable',
    'failure_reason': 'source weights are unreadable',
    'failure_operation': None, 'supported_devices': None,
    'preferred_device': None, 'observed_count': None, 'limit': None}))
raise SystemExit(1)
""")
            output = root / "summary.json"; weights = root / "weights"
            weights.mkdir()
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                        "H3_ANE_INTEGRATION_PROBE": str(probe),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "shadow", "--repo", str(ROOT),
                 "--work-dir", str(root / "work"), "--output", str(output),
                 "--weights", str(weights)], env=env, text=True,
                capture_output=True, check=False)
            self.assertEqual(result.returncode, 1, result.stderr)
            document = json.loads(output.read_text())
            self.assertEqual(document["diagnostic"]["stage"], "artifact")
            self.assertEqual(document["diagnostic"]["code"],
                             "source_weights_unreadable")
            self.assertIsNone(document["receipt"])

    def test_shadow_coordinator_preserves_unchanged_preflight_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter, probe, qualifier = self.fixture_tools(root)
            self.write_tool(converter, """
import json, pathlib, sys
package = pathlib.Path(sys.argv[sys.argv.index('--output') + 1]); package.mkdir()
model = pathlib.Path(sys.argv[sys.argv.index('--compile-output') + 1]); model.mkdir()
pathlib.Path(str(model) + '.qualification.json').write_text(json.dumps({
    'version': 1, 'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'test_vector': 'xorshift32-v1', 'qualified_at': '2026-08-12T00:00:00Z',
    'max_abs': 0.001, 'relative_l2': 0.01, 'status': 'passed'}, sort_keys=True))
print(json.dumps({'source_sha256': 'a' * 64}))
""")
            self.write_tool(qualifier, """
import json, pathlib, sys
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
receipt = pathlib.Path(str(model) + '.qualification.json')
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps({
    'schema': 'h3-ane-qualification/v1', 'status': 'failed',
    'profile': 'shadow-measurement-v1', 'authority': False,
    'measurement_started': False, 'authority_state': 'unchanged',
    'model_sha256': '', 'source_sha256': '', 'max_abs': None,
    'relative_l2': None, 'bounds': {'max_abs': 0.25, 'relative_l2': 0.05},
    'threshold_outcome': False, 'receipt_path': None,
    'failure_stage': 'receipt', 'failure_code': 'receipt_invalid',
    'failure_reason': 'receipt quarantine preflight failed',
    'failure_operation': None, 'supported_devices': None,
    'preferred_device': None, 'observed_count': None, 'limit': None}))
raise SystemExit(2)
""")
            output = root / "summary.json"; weights = root / "weights"
            weights.mkdir(); work = root / "work"
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                        "H3_ANE_INTEGRATION_PROBE": str(probe),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "shadow", "--repo", str(ROOT), "--work-dir", str(work),
                 "--output", str(output), "--weights", str(weights)],
                env=env, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 1, result.stderr)
            document = json.loads(output.read_text())
            self.assertFalse(document["measurement_started"])
            self.assertEqual(document["authority_state"], "unchanged")
            self.assertEqual(document["diagnostic"]["stage"], "receipt")
            receipt = Path(f"{work / 'visual-block.mlmodelc'}.qualification.json")
            self.assertEqual(json.loads(receipt.read_text())["status"], "passed")

    def test_shadow_coordinator_rejects_changed_unchanged_authority_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter, probe, qualifier = self.fixture_tools(root)
            self.write_tool(converter, """
import json, pathlib, sys
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).mkdir()
model = pathlib.Path(sys.argv[sys.argv.index('--compile-output') + 1]); model.mkdir()
pathlib.Path(str(model) + '.qualification.json').write_text('original-authority')
print(json.dumps({'source_sha256': 'a' * 64}))
""")
            self.write_tool(qualifier, """
import json, pathlib, sys
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
pathlib.Path(str(model) + '.qualification.json').write_text('changed-authority')
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps({
    'schema': 'h3-ane-qualification/v1', 'status': 'failed',
    'profile': 'shadow-measurement-v1', 'authority': False,
    'measurement_started': False, 'authority_state': 'unchanged',
    'bounds': {'max_abs': 0.25, 'relative_l2': 0.05},
    'threshold_outcome': False, 'receipt_path': None,
    'failure_stage': 'receipt', 'failure_code': 'receipt_invalid',
    'failure_reason': 'receipt quarantine preflight failed',
    'failure_operation': None, 'supported_devices': None,
    'preferred_device': None, 'observed_count': None, 'limit': None}))
raise SystemExit(2)
""")
            output = root / "summary.json"; weights = root / "weights"
            weights.mkdir(); work = root / "work"
            env = os.environ.copy(); env.update({
                "H3_ANE_INTEGRATION_CONVERTER": str(converter),
                "H3_ANE_INTEGRATION_PROBE": str(probe),
                "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "shadow", "--repo", str(ROOT), "--work-dir", str(work),
                 "--output", str(output), "--weights", str(weights)],
                env=env, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 1)
            document = json.loads(output.read_text())
            self.assertEqual(document["diagnostic"]["code"], "invalid_result")
            self.assertFalse(Path(
                f"{work / 'visual-block.mlmodelc'}.qualification.json").exists())

    def test_production_compute_plan_pairs_propagate_exactly(self):
        production = (ROOT / "h3_ane.m").read_text()
        cases = (
            ("allocation_failed", None, None),
            ("operation_inventory_empty", 0, 0),
            ("operation_inventory_limit_exceeded", 4097, 4096),
            ("operation_nesting_limit_exceeded", 65, 64),
            ("operation_inventory_changed", 150, 149),
        )
        production_tokens = {
            "allocation_failed": "H3_ANE_CODE_ALLOCATION_FAILED",
            "operation_inventory_empty": "H3_ANE_CODE_OPERATION_INVENTORY_EMPTY",
            "operation_inventory_limit_exceeded":
                "H3_ANE_CODE_OPERATION_INVENTORY_LIMIT_EXCEEDED",
            "operation_nesting_limit_exceeded":
                "H3_ANE_CODE_OPERATION_NESTING_LIMIT_EXCEEDED",
            "operation_inventory_changed":
                "H3_ANE_CODE_OPERATION_INVENTORY_CHANGED",
        }
        for code, observed, limit in cases:
            with self.subTest(code=code):
                self.assertIn(production_tokens[code], production)
                diagnostic = self.coordinator.validate_qualification_diagnostic({
                    "failure_stage": "compute_plan", "failure_code": code,
                    "failure_reason": "production compute plan failure",
                    "failure_operation": None, "supported_devices": None,
                    "preferred_device": None, "observed_count": observed,
                    "limit": limit})
                self.assertEqual(diagnostic["stage"], "compute_plan")
                self.assertEqual(diagnostic["code"], code)
                self.assertEqual(diagnostic["observed_count"], observed)
                self.assertEqual(diagnostic["limit"], limit)
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    converter, probe, qualifier = self.fixture_tools(root)
                    self.write_tool(qualifier, f"""
import json, pathlib, sys
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
receipt = pathlib.Path(str(model) + '.qualification.json')
receipt.write_text(json.dumps({{
    'version': 1, 'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'test_vector': 'xorshift32-v1', 'qualified_at': '2026-08-12T00:00:00Z',
    'max_abs': 0.001, 'relative_l2': 0.01, 'status': 'passed'}}))
receipt.unlink()
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps({{
    'schema': 'h3-ane-qualification/v1', 'status': 'failed',
    'profile': 'shadow-measurement-v1', 'authority': False,
    'measurement_started': True, 'authority_state': 'invalidated',
    'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'max_abs': 0.0, 'relative_l2': 0.0,
    'bounds': {{'max_abs': 0.25, 'relative_l2': 0.05}},
    'threshold_outcome': False, 'receipt_path': None,
    'failure_stage': 'compute_plan', 'failure_code': {code!r},
    'failure_reason': 'production compute plan failure',
    'failure_operation': None, 'supported_devices': None,
    'preferred_device': None, 'observed_count': {observed!r},
    'limit': {limit!r}}}))
raise SystemExit(1)
""")
                    output = root / "summary.json"; weights = root / "weights"
                    weights.mkdir()
                    env = os.environ.copy()
                    env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                                "H3_ANE_INTEGRATION_PROBE": str(probe),
                                "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
                    result = subprocess.run(
                        [sys.executable,
                         str(ROOT / "scripts/run_ane_integration.py"), "shadow",
                         "--repo", str(ROOT),
                         "--work-dir", str(root / "work"),
                         "--output", str(output), "--weights", str(weights)],
                        env=env, text=True, capture_output=True, check=False)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    summary = json.loads(output.read_text())
                    self.assertEqual(summary["diagnostic"], diagnostic)
                    self.assertFalse(Path(
                        f"{root / 'work' / 'visual-block.mlmodelc'}.qualification.json").exists())

    def test_oversized_failure_falls_back_to_minimal_atomic_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failure.json"
            self.coordinator.publish_failure(output, {
                "mode": "shadow", "profile": "shadow-measurement-v1",
                "authority": False, "detail": "x" * 20000})
            document = json.loads(output.read_text())
            self.assertEqual(document["status"], "failed")
            self.assertEqual(document["diagnostic"]["code"], "invalid_result")
            self.assertLessEqual(len(output.read_bytes()),
                                 self.coordinator.SUMMARY_LIMIT)
            self.assertFalse(list(output.parent.glob(".failure.json.tmp-*")))

    def test_exact_synthetic_fixture_contract_has_only_eight_pinned_tensors(self):
        self.assertEqual(len(self.coordinator.TENSOR_SHAPES), 8)
        self.assertEqual(self.coordinator.TENSOR_SHAPES[
            "encoder.down.0.block.0.conv1.weight"], (128, 128, 3, 3, 3))

    def test_child_capture_is_bounded_while_pipes_are_drained(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory) / "noisy.py"
            self.write_tool(
                tool, "import sys\nsys.stdout.write('x' * 70000 + 'tail')\n")
            output = self.coordinator.run_command(
                [sys.executable, str(tool)], "noisy")
            self.assertLessEqual(len(output.encode()), self.coordinator.CAPTURE_LIMIT)
            self.assertTrue(output.endswith("tail"))

    def test_real_success_is_sanitized_and_rerunnable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            result, output, _, _ = self.run_real(root, tools)
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(output.read_text())
            self.assertEqual(document["schema"], "h3-ane-integration/v1")
            self.assertEqual(document["inventory"]["total"], 441)
            self.assertEqual(document["receipt"]["status"], "passed")
            self.assertEqual(document["artifacts"]["model_sha256"], "b" * 64)
            self.assertEqual(document["artifacts"]["source_sha256"], "a" * 64)
            self.assertEqual(document["stages"], {
                "conversion": 0, "probe": 0, "qualification": 0})
            result, _, _, _ = self.run_real(root, tools)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(list(root.glob(".summary.json.tmp-*")))

    def test_failure_is_bounded_sanitized_and_has_no_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root, dict(total=441, constant=292,
                nonconstant=149, neural_engine_supported=148, cpu_only=1,
                gpu_only=0, unknown_nonconstant=0, constant_nil_usage=292))
            result, output, _, _ = self.run_real(root, tools)
            self.assertEqual(result.returncode, 1)
            document = json.loads(output.read_text())
            self.assertEqual(document["diagnostic"]["stage"], "eligibility")
            self.assertIsNone(document["receipt"])
            self.assertLessEqual(len(document["diagnostic"]["message"]), 160)
            self.assertNotIn(str(root), output.read_text())

    def test_inventory_is_closed_and_summary_is_size_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = dict(self.coordinator.EXPECTED_INVENTORY, extra=0)
            result, output, _, _ = self.run_real(
                root, self.fixture_tools(root, inventory))
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(output.read_text())["diagnostic"]["stage"],
                             "eligibility")
            oversized = root / "oversized.json"
            with self.assertRaisesRegex(ValueError, "size limit"):
                self.coordinator.atomic_json(
                    oversized, {"value": "x" * self.coordinator.SUMMARY_LIMIT})
            self.assertFalse(oversized.exists())

    def test_output_aliases_are_rejected_before_work_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter, probe, qualifier = self.fixture_tools(root)
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                        "H3_ANE_INTEGRATION_PROBE": str(probe),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
            weights = root / "weights"; weights.mkdir()
            for name in (".", "work", "work/visual-block.mlpackage",
                         "work/visual-block.mlmodelc/inside.json",
                         "work/qualification.json",
                         "work/visual-block.mlmodelc.qualification.json"):
                with self.subTest(output=name):
                    work = root / "work"
                    output = root / name
                    result = subprocess.run(
                        [sys.executable,
                         str(ROOT / "scripts/run_ane_integration.py"), "shadow",
                         "--repo", str(ROOT), "--work-dir", str(work),
                         "--output", str(output), "--weights", str(weights)],
                        env=env, text=True, capture_output=True, check=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(work.exists())

    def test_real_weights_work_and_output_must_be_disjoint_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter, probe, qualifier = self.fixture_tools(root)
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                        "H3_ANE_INTEGRATION_PROBE": str(probe),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
            cases = (
                (root / "weights-a", root / "weights-a" / "work",
                 root / "summary-a.json"),
                (root / "work-b" / "weights", root / "work-b",
                 root / "summary-b.json"),
                (root / "weights-c", root / "work-c", root / "weights-c"),
                (root / "weights-d", root / "work-d",
                 root / "weights-d" / "summary.json"),
            )
            for weights, work, output in cases:
                with self.subTest(weights=weights, work=work, output=output):
                    weights.mkdir(parents=True, exist_ok=True)
                    sentinel = weights / "SOURCE-SENTINEL"
                    sentinel.write_text("preserve")
                    result = subprocess.run(
                        [sys.executable,
                         str(ROOT / "scripts/run_ane_integration.py"), "shadow",
                         "--repo", str(ROOT), "--work-dir", str(work),
                         "--output", str(output), "--weights", str(weights)],
                        env=env, text=True, capture_output=True, check=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(sentinel.read_text(), "preserve")
                    self.assertFalse(output.is_file())

    def test_child_failure_is_stable_and_does_not_publish_private_stderr(self):
        with tempfile.TemporaryDirectory(prefix="private-integration-") as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            self.write_tool(
                tools[0],
                "import pathlib, sys\n"
                "print('failed at ' + str(pathlib.Path.cwd()), file=sys.stderr)\n"
                "raise SystemExit(7)\n")
            result, output, _, _ = self.run_real(root, tools)
            self.assertEqual(result.returncode, 1)
            document = json.loads(output.read_text())
            self.assertEqual(document["diagnostic"], {
                "stage": "conversion", "code": "child_exit_7",
                "message": "conversion child failed"})
            self.assertEqual(document["stages"], {"conversion": 7})
            self.assertNotIn(str(root), output.read_text())

    def test_real_parity_failure_keeps_inventory_and_publishes_no_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            self.write_tool(tools[2], """
import json, pathlib, sys
output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
output.write_text(json.dumps({
    'status': 'failed', 'failure_stage': 'parity',
    'failure_code': 'parity_bounds_failed',
    'failure_reason': 'parity qualification failed',
    'max_abs': 0.19, 'relative_l2': 0.038}))
raise SystemExit(1)
""")
            result, output, _, _ = self.run_real(root, tools)
            self.assertEqual(result.returncode, 1)
            document = json.loads(output.read_text())
            self.assertEqual(document["diagnostic"]["stage"], "parity")
            self.assertEqual(document["diagnostic"]["code"],
                             "parity_bounds_failed")
            self.assertEqual(document["inventory"]["total"], 441)
            self.assertEqual(document["stages"]["qualification"], 1)
            self.assertIsNone(document["receipt"])

    def test_probe_failure_preserves_exact_production_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            self.write_tool(tools[1], """
import json, pathlib, sys
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps({
    'status': 'failed', 'model_sha256': 'b' * 64,
    'source_sha256': 'a' * 64, 'inventory': {'total': 0},
    'diagnostic': {'stage': 'contract', 'code': 'metadata_missing',
                   'message': 'Core ML metadata is missing'}}))
raise SystemExit(1)
""")
            result, output, _, _ = self.run_real(root, tools)
            self.assertEqual(result.returncode, 1)
            document = json.loads(output.read_text())
            self.assertEqual(document["diagnostic"], {
                "stage": "contract", "code": "metadata_missing",
                "message": "Core ML metadata is missing"})
            self.assertEqual(document["stages"], {"conversion": 0, "probe": 1})

    def test_cross_stage_digest_mismatch_cannot_publish_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            self.write_tool(tools[1], """
import json, pathlib, sys
pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps({
    'status': 'passed', 'model_sha256': 'c' * 64,
    'source_sha256': 'd' * 64, 'inventory': {
        'total': 441, 'constant': 292, 'nonconstant': 149,
        'neural_engine_supported': 149, 'cpu_only': 0, 'gpu_only': 0,
        'unknown_nonconstant': 0, 'constant_nil_usage': 292},
    'diagnostic': None}))
""")
            result, output, _, _ = self.run_real(root, tools)
            self.assertEqual(result.returncode, 1)
            document = json.loads(output.read_text())
            self.assertEqual(document["diagnostic"]["stage"], "artifact")
            self.assertEqual(document["diagnostic"]["code"], "digest_mismatch")
            self.assertIsNone(document["receipt"])
            work = root / "work"
            self.assertFalse((work / "qualification.json").exists())
            self.assertFalse(Path(
                f"{work / 'visual-block.mlmodelc'}.qualification.json").exists())

    def test_refuses_existing_unowned_work_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            work = root / "work"; work.mkdir()
            sentinel = work / "unrelated"; sentinel.write_text("preserve")
            result, output, _, _ = self.run_real(root, tools)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(sentinel.exists())
            document = json.loads(output.read_text())
            self.assertEqual(document["diagnostic"]["stage"], "setup")
            self.assertEqual(document["diagnostic"]["code"],
                             "unsafe_work_directory")

    def test_summary_publication_failure_removes_result_and_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            output = root / "output-directory"; output.mkdir()
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(tools[0]),
                        "H3_ANE_INTEGRATION_PROBE": str(tools[1]),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(tools[2])})
            weights = root / "weights"; weights.mkdir()
            work = root / "work"
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "real", "--repo", str(ROOT), "--work-dir", str(work),
                 "--output", str(output), "--weights", str(weights)],
                env=env, text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((work / "qualification.json").exists())
            self.assertFalse(Path(
                f"{work / 'visual-block.mlmodelc'}.qualification.json").exists())

    def test_sigterm_cleans_summary_temp_and_leaves_no_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            self.write_tool(tools[0], "import time\ntime.sleep(30)\n")
            output = root / "summary.json"
            weights = root / "weights"; weights.mkdir()
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(tools[0]),
                        "H3_ANE_INTEGRATION_PROBE": str(tools[1]),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(tools[2])})
            command = [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                       "real", "--repo", str(ROOT),
                       "--work-dir", str(root / "work"), "--output", str(output),
                       "--weights", str(weights)]
            process = subprocess.Popen(command, env=env)
            time.sleep(0.2)
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
            self.assertEqual(process.returncode, 143)
            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob(".summary.json.tmp-*")))

    def test_sigterm_after_qualifier_receipt_removes_uncommitted_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            ready = root / "receipt-ready"
            self.write_tool(tools[2], f"""
import pathlib, sys, time
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
pathlib.Path(str(model) + '.qualification.json').write_text('{{}}')
pathlib.Path({str(ready)!r}).write_text('ready')
time.sleep(30)
""")
            output = root / "summary.json"
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(tools[0]),
                        "H3_ANE_INTEGRATION_PROBE": str(tools[1]),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(tools[2])})
            weights = root / "weights"; weights.mkdir()
            work = root / "work"
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "real", "--repo", str(ROOT), "--work-dir", str(work),
                 "--output", str(output), "--weights", str(weights)], env=env)
            for _ in range(100):
                if ready.exists():
                    break
                time.sleep(0.05)
            self.assertTrue(ready.exists())
            receipt = Path(f"{work / 'visual-block.mlmodelc'}.qualification.json")
            self.assertTrue(receipt.exists())
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
            self.assertEqual(process.returncode, 143)
            self.assertFalse(receipt.exists())
            self.assertFalse(output.exists())

    def test_shadow_sigterm_removes_preexisting_genuine_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            converter, probe, qualifier = self.fixture_tools(root)
            ready = root / "shadow-receipt-ready"
            self.write_tool(qualifier, f"""
import json, pathlib, sys, time
assert '--shadow-only' in sys.argv
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
receipt = pathlib.Path(str(model) + '.qualification.json')
receipt.write_text(json.dumps({{
    'version': 1, 'model_sha256': 'b' * 64, 'source_sha256': 'a' * 64,
    'test_vector': 'xorshift32-v1', 'qualified_at': '2026-08-12T00:00:00Z',
    'max_abs': 0.001, 'relative_l2': 0.01, 'status': 'passed'}}))
pathlib.Path({str(ready)!r}).write_text('ready')
time.sleep(30)
""")
            output = root / "summary.json"; weights = root / "weights"
            weights.mkdir(); work = root / "work"
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(converter),
                        "H3_ANE_INTEGRATION_PROBE": str(probe),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(qualifier)})
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "shadow", "--repo", str(ROOT), "--work-dir", str(work),
                 "--output", str(output), "--weights", str(weights)], env=env)
            for _ in range(100):
                if ready.exists(): break
                time.sleep(0.05)
            self.assertTrue(ready.exists())
            receipt = Path(f"{work / 'visual-block.mlmodelc'}.qualification.json")
            self.assertEqual(json.loads(receipt.read_text())["status"], "passed")
            process.send_signal(signal.SIGTERM); process.wait(timeout=5)
            self.assertEqual(process.returncode, 143)
            self.assertFalse(receipt.exists())
            self.assertFalse(output.exists())

    def test_sigterm_waits_for_child_handler_before_authority_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            ready = root / "qualifier-ready"
            self.write_tool(tools[2], f"""
import pathlib, signal, sys, time
model = pathlib.Path(sys.argv[sys.argv.index('--coreml-model') + 1])
receipt = pathlib.Path(str(model) + '.qualification.json')
def cancelled(*_):
    receipt.write_text('{{}}')
    raise SystemExit(143)
signal.signal(signal.SIGTERM, cancelled)
pathlib.Path({str(ready)!r}).write_text('ready')
time.sleep(30)
""")
            output = root / "summary.json"
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(tools[0]),
                        "H3_ANE_INTEGRATION_PROBE": str(tools[1]),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(tools[2])})
            weights = root / "weights"; weights.mkdir()
            work = root / "work"
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "real", "--repo", str(ROOT), "--work-dir", str(work),
                 "--output", str(output), "--weights", str(weights)], env=env)
            for _ in range(100):
                if ready.exists():
                    break
                time.sleep(0.05)
            self.assertTrue(ready.exists())
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
            receipt = Path(f"{work / 'visual-block.mlmodelc'}.qualification.json")
            self.assertEqual(process.returncode, 143)
            self.assertFalse(receipt.exists())
            self.assertFalse(output.exists())

    def test_sigterm_kills_uncooperative_child_before_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = self.fixture_tools(root)
            ready = root / "converter-ready"
            self.write_tool(tools[0], f"""
import pathlib, signal, time
signal.signal(signal.SIGTERM, lambda *_: None)
pathlib.Path({str(ready)!r}).write_text('ready')
time.sleep(30)
""")
            output = root / "summary.json"
            env = os.environ.copy()
            env.update({"H3_ANE_INTEGRATION_CONVERTER": str(tools[0]),
                        "H3_ANE_INTEGRATION_PROBE": str(tools[1]),
                        "H3_ANE_INTEGRATION_QUALIFIER": str(tools[2])})
            weights = root / "weights"; weights.mkdir()
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts/run_ane_integration.py"),
                 "real", "--repo", str(ROOT), "--work-dir", str(root / "work"),
                 "--output", str(output), "--weights", str(weights)], env=env)
            for _ in range(100):
                if ready.exists():
                    break
                time.sleep(0.05)
            self.assertTrue(ready.exists())
            started = time.monotonic()
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
            self.assertLess(time.monotonic() - started, 4.0)
            self.assertEqual(process.returncode, 143)
            self.assertFalse(output.exists())


class NativeToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(["make", "h3_ane_tool_tests"], cwd=ROOT,
                                text=True, capture_output=True, check=False)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def test_qualification_invalidates_receipt_before_parity_failure(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"first")
            result_path = root / "result.json"
            receipt = Path(f"{model}.qualification.json")
            env = os.environ.copy()
            env.update({
                "H3_ANE_TEST_METRICS": "0.001,0.01",
                "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
            })
            command = [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                       "--coreml-model", str(model), "--output", str(result_path)]
            passed = subprocess.run(command, env=env, text=True,
                                    capture_output=True, check=False)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            first = json.loads(result_path.read_text())
            self.assertEqual(first["status"], "passed")
            for field in ("failure_reason", "failure_stage", "failure_code",
                          "failure_operation", "supported_devices",
                          "preferred_device"):
                self.assertIsNone(first[field])
            self.assertEqual(first["receipt_path"],
                             "compiled-model.qualification.json")
            self.assertNotIn(str(root), json.dumps(first))
            self.assertTrue(receipt.exists())

            (model / "weights.bin").write_bytes(b"changed")
            env["H3_ANE_TEST_METRICS"] = "0.002,0.01"
            failed = subprocess.run(command, env=env, text=True,
                                    capture_output=True, check=False)
            self.assertNotEqual(failed.returncode, 0)
            second = json.loads(result_path.read_text())
            self.assertEqual(second["status"], "failed")
            self.assertEqual(second["failure_stage"], "parity")
            self.assertEqual(second["failure_code"], "parity_bounds_failed")
            self.assertIsNone(second["failure_operation"])
            self.assertIsNone(second["supported_devices"])
            self.assertIsNone(second["preferred_device"])
            self.assertIsNone(second["receipt_path"])
            self.assertNotIn(str(root), json.dumps(second))
            self.assertNotEqual(first["model_sha256"], second["model_sha256"])
            self.assertFalse(receipt.exists())
            self.assertEqual(len(list(receipt.parent.glob(
                receipt.name + ".invalid-*"))), 1)

    def run_shadow(self, root, metrics, *, output=None, extra_env=None):
        root = Path(root)
        model = root / "model.mlmodelc"
        model.mkdir(exist_ok=True)
        (model / "weights.bin").write_bytes(b"model")
        output = output or root / "shadow.json"
        env = os.environ.copy()
        env.update({"H3_ANE_TEST_METRICS": metrics,
                    "H3_ANE_TEST_SOURCE_SHA256": "1" * 64})
        if extra_env:
            env.update(extra_env)
        command = [str(ROOT / "h3_ane_qualification_test"), "--shadow-only",
                   "--model", "unused", "--coreml-model", str(model),
                   "--output", str(output)]
        return subprocess.run(command, env=env, text=True,
                              capture_output=True, check=False), model, Path(output)

    def seed_valid_receipt(self, root):
        root = Path(root)
        model = root / "model.mlmodelc"
        model.mkdir(exist_ok=True)
        (model / "weights.bin").write_bytes(b"model")
        result = subprocess.run(
            [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
             "--coreml-model", str(model), "--output", str(root / "strict.json")],
            env={**os.environ, "H3_ANE_TEST_METRICS": "0.001,0.01",
                 "H3_ANE_TEST_SOURCE_SHA256": "1" * 64},
            text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = Path(f"{model}.qualification.json")
        self.assertEqual(json.loads(receipt.read_text())["status"], "passed")
        return model, receipt

    def test_shadow_bounds_profile_and_strict_threshold_preservation(self):
        cases = [("0.249999,0.049999", 0), ("0.25,0.049", 1),
                 ("0.24,0.05", 1), ("nan,0.01", 1), ("0.1,inf", 1),
                 ("-0.001,0.01", 1), ("0.01,-0.001", 1)]
        for metrics, expected in cases:
            with self.subTest(metrics=metrics), tempfile.TemporaryDirectory() as root:
                _, receipt = self.seed_valid_receipt(root)
                result, model, output = self.run_shadow(root, metrics)
                self.assertEqual(result.returncode, expected, result.stderr)
                document = json.loads(output.read_text())
                self.assertEqual(document["profile"], "shadow-measurement-v1")
                self.assertFalse(document["authority"])
                self.assertEqual(document["bounds"], {
                    "max_abs": 0.25, "relative_l2": 0.05})
                self.assertIsNone(document["receipt_path"])
                self.assertFalse(receipt.exists())
                self.assertEqual(document["failure_stage"],
                                 None if expected == 0 else "parity")
                if "nan" in metrics or "inf" in metrics:
                    self.assertEqual(document["failure_code"],
                                     "parity_metrics_nonfinite")
                elif expected:
                    self.assertEqual(document["failure_code"],
                                     "parity_bounds_failed")
        with tempfile.TemporaryDirectory() as root:
            model, _ = self.seed_valid_receipt(root)
            result, model, shadow_output = self.run_shadow(root, "0.19,0.038")
            self.assertEqual(result.returncode, 0)
            strict = subprocess.run(
                [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                 "--coreml-model", str(model), "--output", str(Path(root) / "strict.json")],
                env={**os.environ, "H3_ANE_TEST_METRICS": "0.19,0.038",
                     "H3_ANE_TEST_SOURCE_SHA256": "1" * 64},
                capture_output=True, check=False)
            self.assertEqual(strict.returncode, 1)
            self.assertFalse(Path(f"{model}.qualification.json").exists())
            strict_document = json.loads((Path(root) / "strict.json").read_text())
            failed_shadow, _, shadow_output = self.run_shadow(root, "0.25,0.01")
            self.assertEqual(failed_shadow.returncode, 1)
            shadow_document = json.loads(shadow_output.read_text())
            for field in ("failure_reason", "failure_stage", "failure_code",
                          "failure_operation", "supported_devices",
                          "preferred_device"):
                self.assertEqual(shadow_document[field], strict_document[field])

    def test_shadow_invalidates_stale_receipt_and_cancellation_is_atomic(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); model, receipt = self.seed_valid_receipt(root)
            result, _, output = self.run_shadow(root, "0.19,0.038")
            self.assertEqual(result.returncode, 0)
            self.assertFalse(receipt.exists())
            self.assertEqual(len(list(receipt.parent.glob(
                receipt.name + ".invalid-*"))), 1)
            output.unlink()
            _, receipt = self.seed_valid_receipt(root)
            marker = root / "synced"
            process_env = {"H3_ANE_TEST_PAUSE_BEFORE_RENAME": str(marker),
                           "H3_ANE_TEST_PAUSE_SUFFIX": "shadow.json"}
            env = {**os.environ, "H3_ANE_TEST_METRICS": "0.19,0.038",
                   "H3_ANE_TEST_SOURCE_SHA256": "1" * 64, **process_env}
            command = [str(ROOT / "h3_ane_qualification_test"), "--shadow-only",
                       "--model", "unused", "--coreml-model", str(model),
                       "--output", str(output)]
            process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            for _ in range(200):
                if marker.exists(): break
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            process.terminate(); process.wait(timeout=5); process.communicate()
            self.assertFalse(output.exists())
            self.assertFalse(receipt.exists())
            self.assertFalse(list(root.glob("shadow.json.tmp-*")))

    def test_shadow_result_write_failure_leaves_no_authority(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); _, receipt = self.seed_valid_receipt(root)
            result, _, _ = self.run_shadow(
                root, "0.19,0.038", output=root / "absent" / "shadow.json")
            self.assertEqual(result.returncode, 2)
            self.assertFalse(receipt.exists())
            self.assertEqual(len(list(receipt.parent.glob(
                receipt.name + ".invalid-*"))), 1)

    def test_shadow_invalidation_rename_conflict_removes_runtime_authority(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); _, receipt = self.seed_valid_receipt(root)
            invalid = Path(f"{receipt}.invalid")
            invalid.mkdir()
            result, _, output = self.run_shadow(root, "0.19,0.038")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["status"], "passed")
            self.assertFalse(receipt.exists())
            self.assertTrue(invalid.is_dir())

    def test_shadow_invalidation_never_modifies_link_targets(self):
        for link_kind in ("symlink", "hardlink"):
            with self.subTest(link_kind=link_kind), tempfile.TemporaryDirectory() as root:
                root = Path(root)
                model = root / "model.mlmodelc"; model.mkdir()
                (model / "weights.bin").write_bytes(b"model")
                sentinel = root / "EXTERNAL-SENTINEL"
                sentinel.write_text("external-authority-must-not-change")
                receipt = Path(f"{model}.qualification.json")
                if link_kind == "symlink":
                    receipt.symlink_to(sentinel)
                else:
                    os.link(sentinel, receipt)
                adversarial = Path(f"{receipt}.invalid"); adversarial.mkdir()
                result, _, output = self.run_shadow(root, "0.19,0.038")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(output.read_text())["status"], "passed")
                self.assertFalse(receipt.exists())
                self.assertEqual(sentinel.read_text(),
                                 "external-authority-must-not-change")
                self.assertTrue(adversarial.is_dir())
                quarantines = list(receipt.parent.glob(receipt.name + ".invalid-*"))
                self.assertEqual(len(quarantines), 1)

    def test_signal_pending_during_invalidation_runs_after_path_is_safe(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); model, receipt = self.seed_valid_receipt(root)
            marker = root / "signals-blocked"; release = root / "release"
            output = root / "shadow.json"
            env = {**os.environ, "H3_ANE_TEST_METRICS": "0.19,0.038",
                   "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                   "H3_ANE_TEST_PAUSE_DURING_INVALIDATION": str(marker),
                   "H3_ANE_TEST_RELEASE_INVALIDATION": str(release)}
            process = subprocess.Popen(
                [str(ROOT / "h3_ane_qualification_test"), "--shadow-only",
                 "--model", "unused", "--coreml-model", str(model),
                 "--output", str(output)], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(200):
                if marker.exists(): break
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            self.assertTrue(receipt.exists())
            process.send_signal(signal.SIGTERM)
            time.sleep(0.05)
            self.assertIsNone(process.poll())
            release.write_text("continue")
            process.wait(timeout=5); process.communicate()
            self.assertEqual(process.returncode, 143)
            self.assertFalse(receipt.exists())
            self.assertFalse(output.exists())
            self.assertEqual(len(list(receipt.parent.glob(
                receipt.name + ".invalid-*"))), 1)

    def test_shadow_receipt_preflight_is_side_effect_free_before_quarantine(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); model, receipt = self.seed_valid_receipt(root)
            original = receipt.read_bytes()
            marker = root / "preflight-complete"; release = root / "release"
            output = root / "shadow.json"
            env = {**os.environ, "H3_ANE_TEST_METRICS": "0.19,0.038",
                   "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                   "H3_ANE_TEST_PAUSE_AFTER_PREFLIGHT": str(marker),
                   "H3_ANE_TEST_RELEASE_PREFLIGHT": str(release)}
            process = subprocess.Popen(
                [str(ROOT / "h3_ane_qualification_test"), "--shadow-only",
                 "--model", "unused", "--coreml-model", str(model),
                 "--output", str(output)], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(200):
                if marker.exists(): break
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            self.assertEqual(receipt.read_bytes(), original)
            self.assertFalse(output.exists())
            self.assertFalse(list(receipt.parent.glob(receipt.name + ".invalid-*")))
            self.assertFalse(list(receipt.parent.glob(receipt.name + ".preflight-*")))
            release.write_text("continue")
            process.wait(timeout=5); process.communicate()
            self.assertEqual(process.returncode, 0)
            self.assertFalse(receipt.exists())

    def test_shadow_preflight_failure_preserves_receipt_and_never_measures(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); model, receipt = self.seed_valid_receipt(root)
            original = receipt.read_bytes(); output = root / "result" / "shadow.json"
            output.parent.mkdir(); marker = root / "MEASUREMENT-MUST-NOT-START"
            os.chmod(model.parent, 0o555)
            try:
                result = subprocess.run(
                    [str(ROOT / "h3_ane_qualification_test"), "--shadow-only",
                     "--model", "unused", "--coreml-model", str(model),
                     "--output", str(output)],
                    env={**os.environ, "H3_ANE_TEST_METRICS": "0.19,0.038",
                         "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                         "H3_ANE_TEST_MEASUREMENT_MARKER": str(marker)},
                    text=True, capture_output=True, check=False)
            finally:
                os.chmod(model.parent, 0o755)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(receipt.read_bytes(), original)
            self.assertFalse(marker.exists())
            document = json.loads(output.read_text())
            self.assertFalse(document["measurement_started"])
            self.assertEqual(document["authority_state"], "unchanged")
            self.assertEqual(document["failure_stage"], "receipt")
            self.assertEqual(document["failure_code"], "receipt_invalid")
            self.assertFalse(list(receipt.parent.glob(receipt.name + ".preflight-*")))

    def test_shadow_post_preflight_invalidation_failure_is_structured(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); model, receipt = self.seed_valid_receipt(root)
            original = receipt.read_bytes(); output = root / "result" / "shadow.json"
            output.parent.mkdir(); marker = root / "preflight-complete"
            release = output.parent / "release"; measurement = output.parent / "measured"
            env = {**os.environ, "H3_ANE_TEST_METRICS": "0.19,0.038",
                   "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                   "H3_ANE_TEST_PAUSE_AFTER_PREFLIGHT": str(marker),
                   "H3_ANE_TEST_RELEASE_PREFLIGHT": str(release),
                   "H3_ANE_TEST_MEASUREMENT_MARKER": str(measurement)}
            process = subprocess.Popen(
                [str(ROOT / "h3_ane_qualification_test"), "--shadow-only",
                 "--model", "unused", "--coreml-model", str(model),
                 "--output", str(output)], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(200):
                if marker.exists(): break
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            os.chmod(model.parent, 0o555)
            try:
                release.write_text("continue")
                process.wait(timeout=5); process.communicate()
            finally:
                os.chmod(model.parent, 0o755)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(receipt.read_bytes(), original)
            self.assertFalse(measurement.exists())
            document = json.loads(output.read_text())
            self.assertFalse(document["measurement_started"])
            self.assertEqual(document["authority_state"], "unchanged")
            self.assertEqual(document["failure_stage"], "receipt")
            self.assertEqual(document["failure_code"], "receipt_invalid")

    def test_result_write_failure_is_stderr_only_and_leaves_no_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            receipt = Path(f"{model}.qualification.json")
            env = os.environ.copy()
            env.update({
                "H3_ANE_TEST_METRICS": "0.001,0.01",
                "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
            })
            result = subprocess.run(
                [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                 "--coreml-model", str(model), "--output", str(root / "absent" / "result.json")],
                env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("publication/result_write_failed", result.stderr)
            self.assertNotIn(str(root), result.stderr)
            self.assertFalse(receipt.exists())

    def test_receipt_write_failure_rewrites_result_without_authority(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            output = root / "result.json"
            receipt = Path(f"{model}.qualification.json")
            env = os.environ.copy()
            env.update({
                "H3_ANE_TEST_METRICS": "0.001,0.01",
                "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                "H3_ANE_TEST_FAIL_RECEIPT_WRITE": "1",
            })
            result = subprocess.run(
                [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                 "--coreml-model", str(model), "--output", str(output)],
                env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 1)
            document = json.loads(output.read_text())
            self.assertEqual(document["status"], "failed")
            self.assertEqual(document["failure_stage"], "publication")
            self.assertEqual(document["failure_code"], "receipt_write_failed")
            self.assertFalse(receipt.exists())

    def test_receipt_rewrite_failure_reports_both_publication_failures(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            output = root / "result.json"
            receipt = Path(f"{model}.qualification.json")
            env = os.environ.copy()
            env.update({
                "H3_ANE_TEST_METRICS": "0.001,0.01",
                "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                "H3_ANE_TEST_FAIL_RECEIPT_WRITE": "1",
                "H3_ANE_TEST_FAIL_RESULT_REWRITE": "1",
            })
            result = subprocess.run(
                [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                 "--coreml-model", str(model), "--output", str(output)],
                env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("publication/receipt_write_failed", result.stderr)
            self.assertIn("publication/result_write_failed", result.stderr)
            self.assertNotIn(str(root), result.stderr)
            self.assertFalse(receipt.exists())

    def test_prehandle_private_path_is_redacted(self):
        with tempfile.TemporaryDirectory(prefix="private-sentinel-") as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            output = root / "result.json"
            result = subprocess.run(
                [str(ROOT / "h3_ane_qualification_test"), "--model",
                 str(root / "PRIVATE-SENTINEL-WEIGHTS"), "--coreml-model",
                 str(model), "--output", str(output)],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            document = json.loads(output.read_text())
            encoded = json.dumps(document)
            self.assertEqual(document["failure_stage"], "artifact")
            self.assertEqual(document["failure_code"], "source_weights_unreadable")
            self.assertNotIn("PRIVATE-SENTINEL", encoded)
            self.assertNotIn(str(root), encoded)

    def test_prehandle_source_failure_survives_null_handle_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="private-source-sentinel-") as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            output = root / "result.json"
            result = subprocess.run(
                [str(ROOT / "h3_ane_qualification_test"), "--model",
                 str(root / "PRIVATE-SOURCE-SENTINEL"), "--coreml-model",
                 str(model), "--output", str(output)],
                text=True, capture_output=True, check=False,
            )
            document = json.loads(output.read_text())
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(document["failure_stage"], "artifact")
            self.assertEqual(document["failure_code"], "source_weights_unreadable")
            self.assertEqual(document["failure_reason"], "source weights are unreadable")
            self.assertNotIn("PRIVATE-SOURCE-SENTINEL", json.dumps(document))

    def test_signal_before_result_rename_removes_temporary_and_authority(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            output = root / "result.json"
            marker = root / "result-synced"
            receipt = Path(f"{model}.qualification.json")
            env = os.environ.copy()
            env.update({
                "H3_ANE_TEST_METRICS": "0.001,0.01",
                "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                "H3_ANE_TEST_PAUSE_BEFORE_RENAME": str(marker),
                "H3_ANE_TEST_PAUSE_SUFFIX": "result.json",
            })
            process = subprocess.Popen(
                [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                 "--coreml-model", str(model), "--output", str(output)], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            import time
            for _ in range(200):
                if marker.exists(): break
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            process.terminate(); process.wait(timeout=5); process.communicate()
            self.assertFalse(output.exists())
            self.assertFalse(receipt.exists())
            self.assertFalse(list(root.glob("result.json.tmp-*")))

    def test_signal_before_receipt_rename_removes_temporary_and_reruns(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); model = root / "model.mlmodelc"; model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            output = root / "result.json"; marker = root / "receipt-synced"
            receipt = Path(f"{model}.qualification.json")
            env = os.environ.copy(); env.update({
                "H3_ANE_TEST_METRICS": "0.001,0.01",
                "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                "H3_ANE_TEST_PAUSE_BEFORE_RENAME": str(marker),
                "H3_ANE_TEST_PAUSE_SUFFIX": ".qualification.json",
            })
            command = [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                       "--coreml-model", str(model), "--output", str(output)]
            process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            import time
            for _ in range(200):
                if marker.exists(): break
                time.sleep(0.01)
            self.assertTrue(marker.exists()); process.terminate(); process.wait(timeout=5)
            process.communicate()
            self.assertTrue(output.exists()); self.assertFalse(receipt.exists())
            self.assertFalse(list(root.glob("*.qualification.json.tmp-*")))
            env.pop("H3_ANE_TEST_PAUSE_BEFORE_RENAME"); env.pop("H3_ANE_TEST_PAUSE_SUFFIX")
            rerun = subprocess.run(command, env=env, capture_output=True, check=False)
            self.assertEqual(rerun.returncode, 0); self.assertTrue(receipt.exists())

    def test_signal_before_result_rewrite_rename_removes_temp_and_reruns(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); model = root / "model.mlmodelc"; model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            output = root / "result.json"; marker = root / "rewrite-synced"
            receipt = Path(f"{model}.qualification.json")
            env = os.environ.copy(); env.update({
                "H3_ANE_TEST_METRICS": "0.001,0.01",
                "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                "H3_ANE_TEST_FAIL_RECEIPT_WRITE": "1",
                "H3_ANE_TEST_PAUSE_BEFORE_RENAME": str(marker),
                "H3_ANE_TEST_PAUSE_SUFFIX": "result.json",
                "H3_ANE_TEST_PAUSE_OCCURRENCE": "2",
            })
            command = [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                       "--coreml-model", str(model), "--output", str(output)]
            process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            import time
            for _ in range(200):
                if marker.exists(): break
                time.sleep(0.01)
            self.assertTrue(marker.exists()); process.terminate(); process.wait(timeout=5)
            process.communicate()
            self.assertFalse(receipt.exists()); self.assertFalse(list(root.glob("result.json.tmp-*")))
            self.assertEqual(json.loads(output.read_text())["status"], "passed")
            for key in ("H3_ANE_TEST_PAUSE_BEFORE_RENAME", "H3_ANE_TEST_PAUSE_SUFFIX",
                        "H3_ANE_TEST_PAUSE_OCCURRENCE"):
                env.pop(key)
            rerun = subprocess.run(command, env=env, capture_output=True, check=False)
            self.assertEqual(rerun.returncode, 1)
            self.assertEqual(json.loads(output.read_text())["failure_code"],
                             "receipt_write_failed")

    def test_receipt_is_final_commit_point_under_post_receipt_signal(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            result_path = root / "result.json"
            marker = root / "receipt-committed"
            receipt = Path(f"{model}.qualification.json")
            env = os.environ.copy()
            env.update({
                "H3_ANE_TEST_METRICS": "0.001,0.01",
                "H3_ANE_TEST_SOURCE_SHA256": "1" * 64,
                "H3_ANE_TEST_PAUSE_AFTER_RECEIPT": str(marker),
            })
            process = subprocess.Popen(
                [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                 "--coreml-model", str(model), "--output", str(result_path)],
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            for _ in range(200):
                if marker.exists():
                    break
                import time
                time.sleep(0.01)
            self.assertTrue(marker.exists(), "tool did not reach receipt commit point")
            process.terminate()
            process.wait(timeout=5)
            process.communicate()
            self.assertTrue(result_path.exists())
            self.assertTrue(receipt.exists())
            self.assertEqual(json.loads(result_path.read_text())["status"], "passed")

    def test_signal_after_invalidation_leaves_no_authorizing_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"model")
            receipt = Path(f"{model}.qualification.json")
            receipt.write_text("old authority")
            marker = root / "invalidated"
            output = root / "result.json"
            env = os.environ.copy()
            env["H3_ANE_TEST_PAUSE_AFTER_INVALIDATION"] = str(marker)
            process = subprocess.Popen(
                [str(ROOT / "h3_ane_qualification_test"), "--model", "unused",
                 "--coreml-model", str(model), "--output", str(output)],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            import time
            for _ in range(200):
                if marker.exists():
                    break
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            process.terminate()
            process.wait(timeout=5)
            process.communicate()
            self.assertFalse(receipt.exists())
            self.assertEqual(len(list(receipt.parent.glob(
                receipt.name + ".invalid-*"))), 1)
            self.assertFalse(list(root.glob("result.json.tmp-*")))

    def test_benchmark_writes_complete_alternating_artifact_atomically(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            model = root / "model.mlmodelc"
            model.mkdir()
            (model / "model.bin").write_bytes(b"fixture")
            output = root / "benchmark.json"
            env = os.environ.copy()
            env.update({
                "H3_ANE_TEST_METAL_SECONDS": "1.0",
                "H3_ANE_TEST_COREML_SECONDS": "0.8",
            })
            command = [str(ROOT / "h3_ane_bench_test"), "--backend", "ab",
                       "--coreml-model", str(model), "--warmup", "2",
                       "--pairs", "20", "--output", str(output)]
            result = subprocess.run(command, env=env, text=True,
                                    capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(output.read_text())
            self.assertEqual(document["placement_summary"],
                             "compute-plan-preference:cpu+neural-engine")
            self.assertNotIn("observed", document["placement_summary"])
            self.assertTrue(self.analyzer_for_native().analyze(document)["claim_passed"])

            output.unlink()
            env["H3_ANE_TEST_ABORT_AFTER"] = "3"
            interrupted = subprocess.run(command, env=env, text=True,
                                         capture_output=True, check=False)
            self.assertNotEqual(interrupted.returncode, 0)
            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob(".benchmark.json.tmp-*")))

    def test_production_binary_ignores_test_environment(self):
        env = os.environ.copy()
        env.update({
            "H3_ANE_TEST_METAL_SECONDS": "1.0",
            "H3_ANE_TEST_COREML_SECONDS": "0.8",
            "H3_ANE_WEIGHT_DIR": "/definitely/absent",
        })
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run(
                [str(ROOT / "h3_ane_bench"), "--backend", "metal",
                 "--pairs", "1", "--output", str(Path(root) / "out.json")],
                env=env, text=True, capture_output=True, check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((Path(root) / "out.json").exists())

    @staticmethod
    def analyzer_for_native():
        return load_script("analyze_ane_benchmark.py")


if __name__ == "__main__":
    unittest.main()
