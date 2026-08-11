#!/usr/bin/env python3
"""Convert the fixed FL2VA visual-encoder block to a Core ML ML Program."""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile


WEIGHT_PREFIX = "encoder.down.0.block.0"
TENSOR_SHAPES = {
    f"{WEIGHT_PREFIX}.norm1.weight": (128,),
    f"{WEIGHT_PREFIX}.norm1.bias": (128,),
    f"{WEIGHT_PREFIX}.conv1.weight": (128, 128, 3, 3, 3),
    f"{WEIGHT_PREFIX}.conv1.bias": (128,),
    f"{WEIGHT_PREFIX}.norm2.weight": (128,),
    f"{WEIGHT_PREFIX}.norm2.bias": (128,),
    f"{WEIGHT_PREFIX}.conv2.weight": (128, 128, 3, 3, 3),
    f"{WEIGHT_PREFIX}.conv2.bias": (128,),
}
BOUNDARY_SHAPE = (1, 1, 256, 256, 128)
_ACTIVE_TEMP = None


def select_block_tensors(weights):
    selected = {}
    for name in sorted(TENSOR_SHAPES):
        if name not in weights:
            raise ValueError(f"required tensor is absent: {name}")
        tensor = weights[name]
        if tuple(tensor.shape) != TENSOR_SHAPES[name]:
            raise ValueError(
                f"tensor {name} shape {tuple(tensor.shape)} does not match "
                f"{TENSOR_SHAPES[name]}")
        selected[name] = tensor
    return selected


def pad_ncdhw_fixture(value):
    """Reference-only tiny-list implementation pinning the graph padding order."""
    result = []
    for batch in value:
        result_batch = []
        for channel in batch:
            height = len(channel[0])
            width = len(channel[0][0])
            zeros = [[0.0] * (width + 2) for _ in range(height + 2)]
            depths = [[row[:] for row in zeros], [row[:] for row in zeros]]
            for plane in channel:
                reflected = []
                row_indices = [1] + list(range(height)) + [height - 2]
                for row_index in row_indices:
                    row = plane[row_index]
                    reflected.append([row[1], *row, row[-2]])
                depths.append(reflected)
            result_batch.append(depths)
        result.append(result_batch)
    return result


def contract_metadata(source_sha256):
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("source SHA-256 must be lowercase hexadecimal")
    return {
        "version": "1",
        "variant": "FL2VA",
        "block_level": "0",
        "block_index": "0",
        "weight_prefix": WEIGHT_PREFIX,
        "boundary_dtype": "F32",
        "shape": ",".join(map(str, BOUNDARY_SHAPE)),
        "source_sha256": source_sha256,
        "h3_ane_boundary_layout": "NDHWC",
        "h3_ane_weight_layout": "OIDHW",
        "h3_ane_group_count": "32",
        "h3_ane_epsilon": "1e-6",
        "h3_ane_temporal_padding": "front=2,back=0,mode=constant",
        "h3_ane_spatial_padding": "1,1,1,1,mode=reflect",
    }


def _u64(value):
    return struct.pack(">Q", value)


def _load_weights_and_digest(directory):
    try:
        import numpy as np
        from safetensors import safe_open
    except ImportError as exc:
        raise RuntimeError(
            "run with Python 3.12, coremltools 9.0, numpy 2.3.2, and "
            "safetensors 0.6.2") from exc
    loaded = {}
    raw = {}
    for path in sorted(Path(directory).glob("*.safetensors")):
        with safe_open(path, framework="np") as stream:
            for name in stream.keys():
                if name not in TENSOR_SHAPES:
                    continue
                if name in loaded:
                    raise ValueError(f"duplicate tensor: {name}")
                tensor = stream.get_tensor(name)
                loaded[name] = tensor
        with path.open("rb") as stream:
            header_length = struct.unpack("<Q", stream.read(8))[0]
            header = json.loads(stream.read(header_length))
            data_start = 8 + header_length
            for name in TENSOR_SHAPES:
                if name not in header:
                    continue
                begin, end = header[name]["data_offsets"]
                stream.seek(data_start + begin)
                raw[name] = (header[name]["dtype"], tuple(header[name]["shape"]),
                             stream.read(end - begin))
    selected = select_block_tensors(loaded)
    digest = hashlib.sha256()
    digest.update(b"h3-ane-tensors-v1")
    digest.update(_u64(len(selected)))
    dtype_ids = {"BF16": 7, "F32": 10}
    for name in sorted(selected):
        dtype, shape, payload = raw[name]
        if dtype not in dtype_ids:
            raise ValueError(f"tensor {name} dtype {dtype} is unsupported")
        encoded = name.encode()
        digest.update(_u64(len(encoded)))
        digest.update(encoded)
        digest.update(_u64(dtype_ids[dtype]))
        digest.update(_u64(len(shape)))
        for dimension in shape:
            digest.update(_u64(dimension))
        digest.update(_u64(len(payload)))
        digest.update(payload)
        selected[name] = np.asarray(selected[name], dtype=np.float32)
    return selected, digest.hexdigest()


def _group_norm(mb, value, weight, bias, name, channels=128, groups=32,
                depth=1, height=256, width=256):
    grouped = mb.reshape(
        x=value, shape=[1, groups, channels // groups, depth * height * width],
        name=f"{name}_reshape")
    mean = mb.reduce_mean(x=grouped, axes=[2, 3], keep_dims=True,
                          name=f"{name}_mean")
    centered = mb.sub(x=grouped, y=mean, name=f"{name}_center")
    variance = mb.reduce_mean(x=mb.square(x=centered), axes=[2, 3],
                              keep_dims=True, name=f"{name}_variance")
    normalized = mb.real_div(
        x=centered,
        y=mb.sqrt(x=mb.add(x=variance, y=1e-6)), name=f"{name}_normalize")
    restored = mb.reshape(x=normalized,
                          shape=[1, channels, depth, height, width])
    scale = weight.reshape((1, channels, 1, 1, 1))
    offset = bias.reshape((1, channels, 1, 1, 1))
    return mb.add(x=mb.mul(x=restored, y=scale), y=offset, name=name)


def _padded_conv(mb, value, weight, bias, name):
    spatial = mb.pad(x=value, pad=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
                     mode="reflect", name=f"{name}_spatial_reflect")
    temporal = mb.pad(x=spatial, pad=[0, 0, 0, 0, 2, 0, 0, 0, 0, 0],
                      mode="constant", constant_val=0.0,
                      name=f"{name}_temporal_front_zero")
    return mb.conv(x=temporal, weight=weight, bias=bias,
                   strides=[1, 1, 1], pad_type="valid", name=name)


def build_program(weights, boundary_shape=BOUNDARY_SHAPE, groups=32):
    import coremltools as ct
    import numpy as np
    from coremltools.converters.mil import Builder as mb

    channels = boundary_shape[4]
    depth, height, width = boundary_shape[1:4]

    @mb.program(input_specs=[mb.TensorSpec(shape=boundary_shape, dtype=ct.converters.mil.mil.types.fp32)],
                opset_version=ct.target.macOS14)
    def program(input):
        ncdhw = mb.transpose(x=input, perm=[0, 4, 1, 2, 3], name="ndhwc_to_ncdhw")
        norm1 = _group_norm(
            mb, ncdhw, weights[f"{WEIGHT_PREFIX}.norm1.weight"],
            weights[f"{WEIGHT_PREFIX}.norm1.bias"], "norm1", channels,
            groups, depth, height, width)
        hidden = _padded_conv(
            mb, mb.silu(x=norm1, name="silu1"),
            weights[f"{WEIGHT_PREFIX}.conv1.weight"],
            weights[f"{WEIGHT_PREFIX}.conv1.bias"], "conv1")
        norm2 = _group_norm(
            mb, hidden, weights[f"{WEIGHT_PREFIX}.norm2.weight"],
            weights[f"{WEIGHT_PREFIX}.norm2.bias"], "norm2", channels,
            groups, depth, height, width)
        output = _padded_conv(
            mb, mb.silu(x=norm2, name="silu2"),
            weights[f"{WEIGHT_PREFIX}.conv2.weight"],
            weights[f"{WEIGHT_PREFIX}.conv2.bias"], "conv2")
        return mb.transpose(x=mb.add(x=output, y=ncdhw, name="residual_add"),
                            perm=[0, 2, 3, 4, 1], name="output")

    return ct.convert(
        program, convert_to="mlprogram",
        inputs=[ct.TensorType(name="input", shape=boundary_shape, dtype=np.float32)],
        outputs=[ct.TensorType(name="output", dtype=np.float32)],
        compute_precision=ct.precision.FLOAT16,
        minimum_deployment_target=ct.target.macOS14,
    )


def _numpy_group_norm(value, weight, bias, groups, epsilon=1e-6):
    import numpy as np
    batch, channels, depth, height, width = value.shape
    grouped = value.reshape(batch, groups, channels // groups,
                            depth * height * width)
    mean = grouped.mean(axis=(2, 3), keepdims=True)
    variance = ((grouped - mean) ** 2).mean(axis=(2, 3), keepdims=True)
    normalized = ((grouped - mean) / np.sqrt(variance + epsilon)).reshape(value.shape)
    return normalized * weight.reshape(1, channels, 1, 1, 1) + \
        bias.reshape(1, channels, 1, 1, 1)


def _numpy_conv(value, weight, bias):
    import numpy as np
    spatial = np.pad(value, ((0, 0), (0, 0), (0, 0), (1, 1), (1, 1)),
                     mode="reflect")
    padded = np.pad(spatial, ((0, 0), (0, 0), (2, 0), (0, 0), (0, 0)),
                    mode="constant")
    output = np.empty((1, weight.shape[0], value.shape[2],
                       value.shape[3], value.shape[4]), dtype=np.float32)
    for channel in range(weight.shape[0]):
        for depth in range(value.shape[2]):
            for row in range(value.shape[3]):
                for column in range(value.shape[4]):
                    window = padded[0, :, depth:depth + 3,
                                    row:row + 3, column:column + 3]
                    output[0, channel, depth, row, column] = \
                        (window * weight[channel]).sum() + bias[channel]
    return output


def run_graph_self_test():
    import coremltools as ct
    import numpy as np
    channels = 32
    shape = (1, 1, 2, 2, channels)
    rng = np.random.default_rng(0x4833414E45)
    weights = {
        f"{WEIGHT_PREFIX}.norm1.weight": np.linspace(0.8, 1.2, channels, dtype=np.float32),
        f"{WEIGHT_PREFIX}.norm1.bias": np.linspace(-0.1, 0.1, channels, dtype=np.float32),
        f"{WEIGHT_PREFIX}.conv1.weight": np.zeros((channels, channels, 3, 3, 3), dtype=np.float32),
        f"{WEIGHT_PREFIX}.conv1.bias": np.linspace(-0.02, 0.02, channels, dtype=np.float32),
        f"{WEIGHT_PREFIX}.norm2.weight": np.linspace(0.9, 1.1, channels, dtype=np.float32),
        f"{WEIGHT_PREFIX}.norm2.bias": np.linspace(0.03, -0.03, channels, dtype=np.float32),
        f"{WEIGHT_PREFIX}.conv2.weight": np.zeros((channels, channels, 3, 3, 3), dtype=np.float32),
        f"{WEIGHT_PREFIX}.conv2.bias": np.linspace(-0.01, 0.01, channels, dtype=np.float32),
    }
    for channel in range(channels):
        weights[f"{WEIGHT_PREFIX}.conv1.weight"][channel, channel, 2, 1, 1] = 0.5
        weights[f"{WEIGHT_PREFIX}.conv2.weight"][channel, channel, 2, 1, 1] = 0.25
    values = rng.standard_normal(shape, dtype=np.float32)
    model = build_program(weights, shape, groups=32)
    model.compute_unit = ct.ComputeUnit.CPU_ONLY
    predicted = model.predict({"input": values})["output"]
    ncdhw = values.transpose(0, 4, 1, 2, 3)
    norm1 = _numpy_group_norm(ncdhw, weights[f"{WEIGHT_PREFIX}.norm1.weight"],
                              weights[f"{WEIGHT_PREFIX}.norm1.bias"], 32)
    hidden = _numpy_conv(norm1 / (1.0 + np.exp(-norm1)),
                         weights[f"{WEIGHT_PREFIX}.conv1.weight"],
                         weights[f"{WEIGHT_PREFIX}.conv1.bias"])
    norm2 = _numpy_group_norm(hidden, weights[f"{WEIGHT_PREFIX}.norm2.weight"],
                              weights[f"{WEIGHT_PREFIX}.norm2.bias"], 32)
    reference = _numpy_conv(norm2 / (1.0 + np.exp(-norm2)),
                            weights[f"{WEIGHT_PREFIX}.conv2.weight"],
                            weights[f"{WEIGHT_PREFIX}.conv2.bias"])
    reference = (reference + ncdhw).transpose(0, 2, 3, 4, 1)
    maximum = float(np.max(np.abs(predicted - reference)))
    if maximum >= 0.002:
        raise RuntimeError(f"deterministic graph self-test max_abs={maximum}")
    return maximum


def _cleanup_temp(*_args):
    global _ACTIVE_TEMP
    if _ACTIVE_TEMP:
        shutil.rmtree(_ACTIVE_TEMP, ignore_errors=True)
    raise KeyboardInterrupt


def _publish_directory(candidate, destination):
    candidate = Path(candidate)
    destination = Path(destination)
    if not destination.exists():
        os.replace(candidate, destination)
        return
    if sys.platform != "darwin":
        raise OSError("atomic directory replacement requires renameatx_np")
    library = ctypes.CDLL(None, use_errno=True)
    renameatx_np = library.renameatx_np
    renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p,
                             ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameatx_np.restype = ctypes.c_int
    at_fdcwd = -2
    rename_swap = 0x00000002
    result = renameatx_np(at_fdcwd, os.fsencode(candidate), at_fdcwd,
                          os.fsencode(destination), rename_swap)
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def atomic_save(model, destination, metadata):
    global _ACTIVE_TEMP
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _ACTIVE_TEMP = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-",
                                        dir=destination.parent))
    package = _ACTIVE_TEMP / destination.name
    try:
        model.user_defined_metadata.update(metadata)
        model.save(package)
        _publish_directory(package, destination)
    finally:
        shutil.rmtree(_ACTIVE_TEMP, ignore_errors=True)
        _ACTIVE_TEMP = None


def compile_package(package, destination, runner=subprocess.run):
    package = Path(package)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(
        prefix=f".{destination.name}.compile-", dir=destination.parent))
    try:
        runner(["xcrun", "coremlcompiler", "compile", str(package),
                str(temporary)], check=True)
        compiled = list(temporary.glob("*.mlmodelc"))
        if len(compiled) != 1:
            raise RuntimeError("coremlcompiler did not produce exactly one .mlmodelc")
        _publish_directory(compiled[0], destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", help="FL2VA visual VAE source directory")
    parser.add_argument("--output", default="ane-visual-block.mlpackage")
    parser.add_argument("--compile-output", help="atomic compiled .mlmodelc destination")
    parser.add_argument("--self-test", action="store_true",
                        help="build and execute a deterministic tiny graph")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGINT, _cleanup_temp)
    signal.signal(signal.SIGTERM, _cleanup_temp)
    try:
        if args.self_test:
            print(json.dumps({"max_abs": run_graph_self_test()}, sort_keys=True))
            return 0
        if not args.weights:
            parser.error("--weights is required unless --self-test is used")
        weights, source_sha256 = _load_weights_and_digest(args.weights)
        model = build_program(weights)
        atomic_save(model, args.output, contract_metadata(source_sha256))
        if args.compile_output:
            compile_package(args.output, args.compile_output)
    except (OSError, RuntimeError, TypeError, ValueError,
            subprocess.CalledProcessError) as exc:
        print(f"convert_ane_visual_block.py: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("convert_ane_visual_block.py: cancelled", file=sys.stderr)
        return 130
    print(json.dumps({"package": args.output, "source_sha256": source_sha256},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
