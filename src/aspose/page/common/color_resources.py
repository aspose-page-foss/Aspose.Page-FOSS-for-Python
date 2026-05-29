"""Color space, function, and pattern resources for render outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from .render_model import RenderCommand


@dataclass(frozen=True)
class DeviceColorSpace:
    name: str


@dataclass(frozen=True)
class IndexedColorSpace:
    base: "ColorSpace"
    hival: int
    lookup: bytes


@dataclass(frozen=True)
class SeparationColorSpace:
    name: str
    alternate: "ColorSpace"
    tint: "Function"


@dataclass(frozen=True)
class DeviceNColorSpace:
    names: list[str]
    alternate: "ColorSpace"
    tint: "Function"


@dataclass(frozen=True)
class CieBasedColorSpace:
    icc_profile: bytes
    components: int
    ranges: tuple[float, ...] | None = None


@dataclass(frozen=True)
class PatternColorSpace:
    base: "ColorSpace | None"


ColorSpace = Union[
    DeviceColorSpace,
    IndexedColorSpace,
    SeparationColorSpace,
    DeviceNColorSpace,
    CieBasedColorSpace,
    PatternColorSpace,
]


@dataclass(frozen=True)
class SampledFunction:
    domain: list[float]
    range: list[float]
    size: list[int]
    bits_per_sample: int
    order: int
    encode: list[float]
    decode: list[float]
    samples: bytes

    def evaluate(self, inputs: list[float]) -> list[float]:
        input_count = len(self.domain) // 2
        if len(inputs) != input_count:
            raise ValueError("sampled function input count mismatch")
        outputs = len(self.range) // 2
        samples = _decode_samples(self.samples, self.bits_per_sample)
        indices = []
        for idx in range(input_count):
            d0 = self.domain[idx * 2]
            d1 = self.domain[idx * 2 + 1]
            value = _clamp(inputs[idx], d0, d1)
            e0 = self.encode[idx * 2] if self.encode else d0
            e1 = self.encode[idx * 2 + 1] if self.encode else d1
            if d1 == d0:
                mapped = e0
            else:
                mapped = e0 + (value - d0) * (e1 - e0) / (d1 - d0)
            size = self.size[idx]
            if size <= 1:
                indices.append(0)
            else:
                pos = (mapped - e0) / (e1 - e0) if e1 != e0 else 0.0
                indices.append(int(round(_clamp(pos, 0.0, 1.0) * (size - 1))))
        sample_index = 0
        multiplier = 1
        for idx, size in zip(reversed(indices), reversed(self.size)):
            sample_index += idx * multiplier
            multiplier *= size
        start = sample_index * outputs
        results: list[float] = []
        max_sample = (1 << self.bits_per_sample) - 1
        for out_idx in range(outputs):
            raw = samples[start + out_idx]
            d0 = self.decode[out_idx * 2] if self.decode else self.range[out_idx * 2]
            d1 = self.decode[out_idx * 2 + 1] if self.decode else self.range[out_idx * 2 + 1]
            if max_sample == 0:
                value = d0
            else:
                value = d0 + (raw / max_sample) * (d1 - d0)
            r0 = self.range[out_idx * 2]
            r1 = self.range[out_idx * 2 + 1]
            results.append(_clamp(value, r0, r1))
        return results


@dataclass(frozen=True)
class ExponentialFunction:
    domain: list[float]
    range: list[float]
    c0: list[float]
    c1: list[float]
    n: float

    def evaluate(self, inputs: list[float]) -> list[float]:
        if not inputs:
            raise ValueError("exponential function requires one input")
        x = _clamp(inputs[0], self.domain[0], self.domain[1])
        results: list[float] = []
        for idx, (c0, c1) in enumerate(zip(self.c0, self.c1)):
            value = c0 + (x ** self.n) * (c1 - c0)
            r0 = self.range[idx * 2]
            r1 = self.range[idx * 2 + 1]
            results.append(_clamp(value, r0, r1))
        return results


@dataclass(frozen=True)
class StitchingFunction:
    domain: list[float]
    range: list[float]
    functions: list["Function"]
    bounds: list[float]
    encode: list[float]

    def evaluate(self, inputs: list[float]) -> list[float]:
        if not inputs:
            raise ValueError("stitching function requires one input")
        x = _clamp(inputs[0], self.domain[0], self.domain[1])
        segments = [self.domain[0]] + self.bounds + [self.domain[1]]
        index = 0
        for idx in range(len(segments) - 1):
            if segments[idx] <= x <= segments[idx + 1]:
                index = idx
                break
        func = self.functions[index]
        e0 = self.encode[index * 2]
        e1 = self.encode[index * 2 + 1]
        d0 = segments[index]
        d1 = segments[index + 1]
        if d1 == d0:
            mapped = e0
        else:
            mapped = e0 + (x - d0) * (e1 - e0) / (d1 - d0)
        return func.evaluate([mapped])


Function = Union[SampledFunction, ExponentialFunction, StitchingFunction]


@dataclass(frozen=True)
class AxialShading:
    color_space: ColorSpace
    coords: tuple[float, float, float, float]
    domain: tuple[float, float] | None
    function: Function
    extend: tuple[bool, bool]


@dataclass(frozen=True)
class RadialShading:
    color_space: ColorSpace
    coords: tuple[float, float, float, float, float, float]
    domain: tuple[float, float] | None
    function: Function
    extend: tuple[bool, bool]


Shading = Union[AxialShading, RadialShading]


@dataclass(frozen=True)
class TilingPattern:
    paint_type: int
    tiling_type: int
    bbox: tuple[float, float, float, float]
    x_step: float
    y_step: float
    matrix: tuple[float, float, float, float, float, float]
    commands: list["RenderCommand"]


@dataclass(frozen=True)
class ShadingPattern:
    shading: Shading
    matrix: tuple[float, float, float, float, float, float]


Pattern = Union[TilingPattern, ShadingPattern]


@dataclass(frozen=True)
class ColorSpacePaint:
    space_id: str
    components: tuple[float, ...]


@dataclass(frozen=True)
class PatternPaint:
    pattern_id: str
    base_space_id: str | None
    base_components: tuple[float, ...] | None


def _decode_samples(data: bytes, bits: int) -> list[int]:
    if bits <= 0:
        raise ValueError("bits per sample must be positive")
    max_value = (1 << bits) - 1
    result: list[int] = []
    buffer = 0
    buffer_bits = 0
    for byte in data:
        buffer = (buffer << 8) | byte
        buffer_bits += 8
        while buffer_bits >= bits:
            shift = buffer_bits - bits
            value = (buffer >> shift) & max_value
            result.append(value)
            buffer_bits -= bits
            buffer &= (1 << buffer_bits) - 1 if buffer_bits > 0 else 0
    return result


def _clamp(value: float, lower: float, upper: float) -> float:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value
