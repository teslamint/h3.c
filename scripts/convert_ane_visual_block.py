#!/usr/bin/env python3
"""Convert the fixed FL2VA visual-encoder block to a Core ML ML Program."""

import argparse
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
        "h3_ane_contract_version": "1",
        "h3_ane_variant": "FL2VA",
        "h3_ane_block_level": "0",
        "h3_ane_block_index": "0",
        "h3_ane_weight_prefix": WEIGHT_PREFIX,
        "h3_ane_boundary_dtype": "F32",
        "h3_ane_shape": ",".join(map(str, BOUNDARY_SHAPE)),
        "h3_ane_boundary_layout": "NDHWC",
        "h3_ane_weight_layout": "OIDHW",
        "h3_ane_group_count": "32",
        "h3_ane_epsilon": "1e-6",
        "h3_ane_temporal_padding": "front=2,back=0,mode=constant",
        "h3_ane_spatial_padding": "1,1,1,1,mode=reflect",
        "h3_ane_source_sha256": source_sha256,
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


def _group_norm(mb, value, weight, bias, name):
    grouped = mb.reshape(x=value, shape=[1, 32, 4, 256 * 256], name=f"{name}_reshape")
    mean = mb.reduce_mean(x=grouped, axes=[2, 3], keep_dims=True,
                          name=f"{name}_mean")
    centered = mb.sub(x=grouped, y=mean, name=f"{name}_center")
    variance = mb.reduce_mean(x=mb.square(x=centered), axes=[2, 3],
                              keep_dims=True, name=f"{name}_variance")
    normalized = mb.real_div(
        x=centered,
        y=mb.sqrt(x=mb.add(x=variance, y=1e-6)), name=f"{name}_normalize")
    restored = mb.reshape(x=normalized, shape=[1, 128, 1, 256, 256])
    scale = weight.reshape((1, 128, 1, 1, 1))
    offset = bias.reshape((1, 128, 1, 1, 1))
    return mb.add(x=mb.mul(x=restored, y=scale), y=offset, name=name)


def _padded_conv(mb, value, weight, bias, name):
    spatial = mb.pad(x=value, pad=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
                     mode="reflect", name=f"{name}_spatial_reflect")
    temporal = mb.pad(x=spatial, pad=[0, 0, 0, 0, 2, 0, 0, 0, 0, 0],
                      mode="constant", constant_val=0.0,
                      name=f"{name}_temporal_front_zero")
    return mb.conv(x=temporal, weight=weight, bias=bias,
                   strides=[1, 1, 1], pad_type="valid", name=name)


def build_program(weights):
    import coremltools as ct
    import numpy as np
    from coremltools.converters.mil import Builder as mb

    @mb.program(input_specs=[mb.TensorSpec(shape=BOUNDARY_SHAPE, dtype=ct.converters.mil.mil.types.fp32)],
                opset_version=ct.target.macOS14)
    def program(input):
        ncdhw = mb.transpose(x=input, perm=[0, 4, 1, 2, 3], name="ndhwc_to_ncdhw")
        norm1 = _group_norm(mb, ncdhw, weights[f"{WEIGHT_PREFIX}.norm1.weight"],
                            weights[f"{WEIGHT_PREFIX}.norm1.bias"], "norm1")
        hidden = _padded_conv(
            mb, mb.silu(x=norm1, name="silu1"),
            weights[f"{WEIGHT_PREFIX}.conv1.weight"],
            weights[f"{WEIGHT_PREFIX}.conv1.bias"], "conv1")
        norm2 = _group_norm(mb, hidden, weights[f"{WEIGHT_PREFIX}.norm2.weight"],
                            weights[f"{WEIGHT_PREFIX}.norm2.bias"], "norm2")
        output = _padded_conv(
            mb, mb.silu(x=norm2, name="silu2"),
            weights[f"{WEIGHT_PREFIX}.conv2.weight"],
            weights[f"{WEIGHT_PREFIX}.conv2.bias"], "conv2")
        return mb.transpose(x=mb.add(x=output, y=ncdhw, name="residual_add"),
                            perm=[0, 2, 3, 4, 1], name="output")

    return ct.convert(
        program, convert_to="mlprogram",
        inputs=[ct.TensorType(name="input", shape=BOUNDARY_SHAPE, dtype=np.float32)],
        outputs=[ct.TensorType(name="output", dtype=np.float32)],
        compute_precision=ct.precision.FLOAT16,
        minimum_deployment_target=ct.target.macOS14,
    )


def _cleanup_temp(*_args):
    global _ACTIVE_TEMP
    if _ACTIVE_TEMP:
        shutil.rmtree(_ACTIVE_TEMP, ignore_errors=True)
    raise KeyboardInterrupt


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
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(package, destination)
    finally:
        shutil.rmtree(_ACTIVE_TEMP, ignore_errors=True)
        _ACTIVE_TEMP = None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", required=True, help="FL2VA visual VAE source directory")
    parser.add_argument("--output", default="ane-visual-block.mlpackage")
    parser.add_argument("--compile-output", help="directory passed to coremlcompiler compile")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGINT, _cleanup_temp)
    signal.signal(signal.SIGTERM, _cleanup_temp)
    try:
        weights, source_sha256 = _load_weights_and_digest(args.weights)
        model = build_program(weights)
        atomic_save(model, args.output, contract_metadata(source_sha256))
        if args.compile_output:
            subprocess.run(["xcrun", "coremlcompiler", "compile", args.output,
                            args.compile_output], check=True)
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
