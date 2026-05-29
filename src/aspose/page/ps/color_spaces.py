"""PostScript color space parsing."""

from __future__ import annotations

from pathlib import Path

from .errors import PsRangeError, PsTypeError
from .functions import parse_function
from .objects import PsArray, PsDict, PsName, PsObject, PsString
from ..common.color_resources import (
    CieBasedColorSpace,
    ColorSpace,
    DeviceColorSpace,
    DeviceNColorSpace,
    IndexedColorSpace,
    PatternColorSpace,
    SeparationColorSpace,
)
from ..common.render_model import RenderModelBuilder


def parse_color_space(obj: PsObject, builder: RenderModelBuilder) -> ColorSpace:
    if isinstance(obj, PsName):
        return _device_space(obj.value)
    if isinstance(obj, str):
        return _device_space(obj)
    if not isinstance(obj, PsArray):
        raise PsTypeError("color space must be name or array")
    if not obj.items:
        raise PsRangeError("empty color space array")
    tag = obj.items[0]
    if isinstance(tag, PsName):
        tag_name = tag.value
    elif isinstance(tag, str):
        tag_name = tag
    else:
        raise PsTypeError("invalid color space tag")
    if tag_name == "Indexed":
        return _parse_indexed(obj, builder)
    if tag_name == "Separation":
        return _parse_separation(obj, builder)
    if tag_name == "DeviceN":
        return _parse_devicen(obj, builder)
    if tag_name.startswith("CIEBased"):
        return _parse_cie(obj)
    if tag_name == "Pattern":
        base = None
        if len(obj.items) > 1:
            base = parse_color_space(obj.items[1], builder)
        return PatternColorSpace(base=base)
    return _device_space(tag_name)


def load_default_icc_profile() -> bytes:
    path = Path(__file__).resolve().parents[4] / "resources" / "sRGB_IEC61966-2-1_black_scaled.icc"
    return path.read_bytes()


def _device_space(name: str) -> ColorSpace:
    if name in ("DeviceRGB", "DeviceCMYK", "DeviceGray"):
        return DeviceColorSpace(name=name)
    raise PsTypeError(f"unsupported device color space {name}")


def _parse_indexed(array: PsArray, builder: RenderModelBuilder) -> ColorSpace:
    if len(array.items) < 4:
        raise PsRangeError("Indexed color space requires base, hival, lookup")
    base = parse_color_space(array.items[1], builder)
    hival = array.items[2]
    if not isinstance(hival, (int, float)):
        raise PsTypeError("Indexed hival must be numeric")
    lookup = array.items[3]
    if isinstance(lookup, PsString):
        data = lookup.value
    elif isinstance(lookup, bytes):
        data = lookup
    elif isinstance(lookup, PsArray):
        values = []
        for item in lookup.items:
            if not isinstance(item, (int, float)):
                raise PsTypeError("Indexed lookup array must be numeric")
            values.append(int(item) & 0xFF)
        data = bytes(values)
    else:
        raise PsTypeError("Indexed lookup must be string or array")
    return IndexedColorSpace(base=base, hival=int(hival), lookup=data)


def _parse_separation(array: PsArray, builder: RenderModelBuilder) -> ColorSpace:
    if len(array.items) < 4:
        raise PsRangeError("Separation color space requires name, alternate, tint")
    name_value = _coerce_colorant_name(array.items[1])
    alternate = parse_color_space(array.items[2], builder)
    tint = parse_function(array.items[3], builder)
    return SeparationColorSpace(name=name_value, alternate=alternate, tint=tint)


def _parse_devicen(array: PsArray, builder: RenderModelBuilder) -> ColorSpace:
    if len(array.items) < 4:
        raise PsRangeError("DeviceN color space requires names, alternate, tint")
    names_value = array.items[1]
    if not isinstance(names_value, PsArray):
        raise PsTypeError("DeviceN names must be array")
    names: list[str] = []
    for entry in names_value.items:
        names.append(_coerce_colorant_name(entry))
    alternate = parse_color_space(array.items[2], builder)
    tint = parse_function(array.items[3], builder)
    return DeviceNColorSpace(names=names, alternate=alternate, tint=tint)


def _parse_cie(array: PsArray) -> ColorSpace:
    if len(array.items) < 2:
        raise PsRangeError("CIEBased color space requires dictionary")
    data = array.items[1]
    if not isinstance(data, PsDict):
        raise PsTypeError("CIEBased requires dictionary")
    components = 3
    n_value = data.items.get("N")
    if isinstance(n_value, (int, float)):
        components = int(n_value)
    ranges: tuple[float, ...] | None = None
    ranges_value = data.items.get("RangeABC") or data.items.get("RangeLMN")
    if isinstance(ranges_value, PsArray):
        parsed: list[float] = []
        for item in ranges_value.items:
            if isinstance(item, (int, float)):
                parsed.append(float(item))
        if len(parsed) >= 2:
            ranges = tuple(parsed)
    icc = data.items.get("ICCProfile") or data.items.get("Profile") or data.items.get("DataSource")
    if isinstance(icc, PsString):
        profile = icc.value
    elif isinstance(icc, bytes):
        profile = icc
    else:
        profile = load_default_icc_profile()
    return CieBasedColorSpace(icc_profile=profile, components=components, ranges=ranges)


def _coerce_colorant_name(value: object) -> str:
    if isinstance(value, PsName):
        return value.value
    if isinstance(value, str):
        return value
    if isinstance(value, PsString):
        return value.value.decode("latin-1", errors="ignore")
    if isinstance(value, bytes):
        return value.decode("latin-1", errors="ignore")
    raise PsTypeError("Separation/DeviceN colorant name must be name or string")
