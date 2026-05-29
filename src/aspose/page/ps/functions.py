"""PostScript function parsing utilities."""

from __future__ import annotations

from .errors import PsRangeError, PsTypeError
from .objects import PsArray, PsDict, PsName, PsObject, PsProcedure, PsString
from ..common.color_resources import (
    ExponentialFunction,
    Function,
    SampledFunction,
    StitchingFunction,
)
from ..common.render_model import RenderModelBuilder


def parse_function(obj: PsObject, builder: RenderModelBuilder) -> Function:
    if isinstance(obj, PsProcedure):
        function = _parse_procedure_tint(obj)
        builder.register_function(function)
        return function
    if not isinstance(obj, PsDict):
        raise PsTypeError("function dictionary expected")
    ftype = obj.items.get("FunctionType")
    if not isinstance(ftype, (int, float)):
        raise PsTypeError("FunctionType must be numeric")
    ftype = int(ftype)
    if ftype == 0:
        function = _parse_sampled(obj)
    elif ftype == 2:
        function = _parse_exponential(obj)
    elif ftype == 3:
        function = _parse_stitching(obj, builder)
    else:
        raise PsRangeError(f"unsupported FunctionType {ftype}")
    builder.register_function(function)
    return function


def _parse_procedure_tint(proc: PsProcedure) -> ExponentialFunction:
    # PostScript tint transforms in Separation/DeviceN are often simple
    # procedures (eg `{ 0 exch 0 0 }`), not PDF function dictionaries.
    c0 = _eval_tint_procedure(proc, 0.0)
    c1 = _eval_tint_procedure(proc, 1.0)
    if not c0 or len(c0) != len(c1):
        raise PsTypeError("unsupported tint transform procedure")
    range_values: list[float] = []
    for v0, v1 in zip(c0, c1):
        lo = min(v0, v1, 0.0)
        hi = max(v0, v1, 1.0)
        range_values.extend([lo, hi])
    return ExponentialFunction(
        domain=[0.0, 1.0],
        range=range_values,
        c0=c0,
        c1=c1,
        n=1.0,
    )


def _eval_tint_procedure(proc: PsProcedure, tint: float) -> list[float]:
    stack: list[float] = [float(tint)]
    for item in proc.items:
        if isinstance(item, (int, float)):
            stack.append(float(item))
            continue
        if isinstance(item, PsName):
            if item.literal:
                raise PsTypeError("unsupported literal name in tint procedure")
            _eval_tint_operator(item.value, stack)
            continue
        raise PsTypeError("unsupported tint transform procedure")
    return stack


def _eval_tint_operator(name: str, stack: list[float]) -> None:
    if name == "add":
        b = stack.pop()
        a = stack.pop()
        stack.append(a + b)
        return
    if name == "sub":
        b = stack.pop()
        a = stack.pop()
        stack.append(a - b)
        return
    if name == "mul":
        b = stack.pop()
        a = stack.pop()
        stack.append(a * b)
        return
    if name == "div":
        b = stack.pop()
        a = stack.pop()
        stack.append(a / b)
        return
    if name == "neg":
        stack.append(-stack.pop())
        return
    if name == "abs":
        stack.append(abs(stack.pop()))
        return
    if name == "dup":
        stack.append(stack[-1])
        return
    if name == "exch":
        stack[-1], stack[-2] = stack[-2], stack[-1]
        return
    if name == "pop":
        stack.pop()
        return
    raise PsTypeError(f"unsupported tint procedure operator: {name}")


def _parse_sampled(data: PsDict) -> SampledFunction:
    domain = _require_number_list(data, "Domain")
    range_values = _require_number_list(data, "Range")
    size = _require_int_list(data, "Size")
    bits = _require_int(data, "BitsPerSample")
    order = int(data.items.get("Order", 1))
    encode = _optional_number_list(data, "Encode") or _default_encode(domain)
    decode = _optional_number_list(data, "Decode") or list(range_values)
    source = data.items.get("DataSource")
    if isinstance(source, PsString):
        samples = source.value
    elif isinstance(source, bytes):
        samples = source
    else:
        raise PsTypeError("DataSource must be string or bytes")
    return SampledFunction(
        domain=domain,
        range=range_values,
        size=size,
        bits_per_sample=bits,
        order=order,
        encode=encode,
        decode=decode,
        samples=samples,
    )


def _parse_exponential(data: PsDict) -> ExponentialFunction:
    domain = _require_number_list(data, "Domain")
    range_values = _require_number_list(data, "Range")
    c0 = _optional_number_list(data, "C0") or [0.0] * (len(range_values) // 2)
    c1 = _optional_number_list(data, "C1") or [1.0] * (len(range_values) // 2)
    n = data.items.get("N")
    if not isinstance(n, (int, float)):
        raise PsTypeError("N must be numeric")
    return ExponentialFunction(
        domain=domain,
        range=range_values,
        c0=c0,
        c1=c1,
        n=float(n),
    )


def _parse_stitching(data: PsDict, builder: RenderModelBuilder) -> StitchingFunction:
    domain = _require_number_list(data, "Domain")
    range_values = _require_number_list(data, "Range")
    functions_obj = data.items.get("Functions")
    if not isinstance(functions_obj, PsArray):
        raise PsTypeError("Functions must be array")
    functions = [parse_function(item, builder) for item in functions_obj.items]
    bounds = _require_number_list(data, "Bounds")
    encode = _require_number_list(data, "Encode")
    return StitchingFunction(
        domain=domain,
        range=range_values,
        functions=functions,
        bounds=bounds,
        encode=encode,
    )


def _require_number_list(data: PsDict, key: str) -> list[float]:
    value = data.items.get(key)
    if not isinstance(value, PsArray):
        raise PsTypeError(f"{key} must be array")
    result: list[float] = []
    for item in value.items:
        if not isinstance(item, (int, float)):
            raise PsTypeError(f"{key} must be numeric array")
        result.append(float(item))
    return result


def _optional_number_list(data: PsDict, key: str) -> list[float] | None:
    value = data.items.get(key)
    if value is None:
        return None
    if not isinstance(value, PsArray):
        raise PsTypeError(f"{key} must be array")
    result: list[float] = []
    for item in value.items:
        if not isinstance(item, (int, float)):
            raise PsTypeError(f"{key} must be numeric array")
        result.append(float(item))
    return result


def _require_int_list(data: PsDict, key: str) -> list[int]:
    values = _require_number_list(data, key)
    return [int(value) for value in values]


def _require_int(data: PsDict, key: str) -> int:
    value = data.items.get(key)
    if not isinstance(value, (int, float)):
        raise PsTypeError(f"{key} must be numeric")
    return int(value)


def _default_encode(domain: list[float]) -> list[float]:
    encode = []
    for i in range(0, len(domain), 2):
        encode.extend([domain[i], domain[i + 1]])
    return encode
