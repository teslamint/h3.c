#!/usr/bin/env python3
"""Build the exact five-dimensional design candidate for eligibility probing."""

import argparse
import importlib.util
from pathlib import Path
import shutil

import coremltools as ct
import numpy as np
from coremltools.converters.mil import Builder as mb


def load_converter(repo):
    path = repo / "scripts/convert_ane_visual_block.py"
    spec = importlib.util.spec_from_file_location("h3_ane_converter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(repo, weights_path, package, compiled):
    converter = load_converter(repo)
    weights, digest = converter._load_weights_and_digest(weights_path)
    prefix = converter.WEIGHT_PREFIX
    shape = converter.BOUNDARY_SHAPE

    def group_norm(value, weight, bias, name):
        parts = []
        for group in range(32):
            begin = group * 4
            part = mb.slice_by_index(
                x=value, begin=[0, 0, 0, begin],
                end=[1, 256, 256, begin + 4], name=f"{name}_slice_{group}")
            parts.append(mb.layer_norm(
                x=part, axes=[1, 2, 3], epsilon=1e-6,
                name=f"{name}_group_{group}"))
        normalized = mb.concat(values=parts, axis=3, name=f"{name}_concat")
        scale = weight.reshape((1, 1, 1, 128))
        offset = bias.reshape((1, 1, 1, 128))
        return mb.add(
            x=mb.mul(x=normalized, y=scale, name=f"{name}_scale"),
            y=offset, name=name)

    def conv2d(value, weight, bias, name):
        nchw = mb.transpose(x=value, perm=[0, 3, 1, 2],
                            name=f"{name}_to_nchw")
        padded = mb.pad(x=nchw, pad=[0, 0, 0, 0, 1, 1, 1, 1],
                        mode="reflect", name=f"{name}_reflect")
        # At D=1 after temporal padding [front=2, back=0], only OIDHW
        # temporal plane 2 can contribute to the single output depth.
        kernel = weight[:, :, 2, :, :]
        result = mb.conv(x=padded, weight=kernel, bias=bias,
                         pad_type="valid", name=name)
        return mb.transpose(x=result, perm=[0, 2, 3, 1],
                            name=f"{name}_to_nhwc")

    @mb.program(
        input_specs=[mb.TensorSpec(
            shape=shape, dtype=ct.converters.mil.mil.types.fp32)],
        opset_version=ct.target.macOS14)
    def program(input):
        value = mb.squeeze(x=input, axes=[1], name="remove_depth")
        norm1 = group_norm(
            value, weights[f"{prefix}.norm1.weight"],
            weights[f"{prefix}.norm1.bias"], "norm1")
        hidden = conv2d(
            mb.silu(x=norm1, name="silu1"),
            weights[f"{prefix}.conv1.weight"],
            weights[f"{prefix}.conv1.bias"], "conv1")
        norm2 = group_norm(
            hidden, weights[f"{prefix}.norm2.weight"],
            weights[f"{prefix}.norm2.bias"], "norm2")
        output = conv2d(
            mb.silu(x=norm2, name="silu2"),
            weights[f"{prefix}.conv2.weight"],
            weights[f"{prefix}.conv2.bias"], "conv2")
        residual = mb.add(x=value, y=output, name="residual")
        return mb.expand_dims(x=residual, axes=[1], name="restore_depth")

    model = ct.convert(
        program, convert_to="mlprogram",
        inputs=[ct.TensorType(name="input", shape=shape, dtype=np.float32)],
        outputs=[ct.TensorType(name="output", dtype=np.float32)],
        compute_precision=ct.precision.FLOAT16,
        minimum_deployment_target=ct.target.macOS14)
    for path in (package, compiled):
        if path.exists():
            shutil.rmtree(path)
    converter.atomic_save(model, package, converter.contract_metadata(digest))
    converter.compile_package(package, compiled)
    print(digest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--compiled", type=Path, required=True)
    args = parser.parse_args()
    build(args.repo.resolve(), args.weights.resolve(), args.package, args.compiled)


if __name__ == "__main__":
    main()
