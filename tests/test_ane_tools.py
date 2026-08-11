import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import os


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
            self.assertTrue(receipt.exists())

            (model / "weights.bin").write_bytes(b"changed")
            env["H3_ANE_TEST_METRICS"] = "0.002,0.01"
            failed = subprocess.run(command, env=env, text=True,
                                    capture_output=True, check=False)
            self.assertNotEqual(failed.returncode, 0)
            second = json.loads(result_path.read_text())
            self.assertEqual(second["status"], "failed")
            self.assertNotEqual(first["model_sha256"], second["model_sha256"])
            self.assertFalse(receipt.exists())
            self.assertTrue(Path(f"{receipt}.invalid").exists())

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
            self.assertTrue(Path(f"{receipt}.invalid").exists())
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
                             "observed:cpu+neural-engine")
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
