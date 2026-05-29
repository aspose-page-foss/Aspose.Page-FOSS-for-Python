"""Base PostScript operators (stack, math, dict, control)."""

from __future__ import annotations

import math

from .context import ExecutionContext
from .errors import PsError, PsQuit, PsRangeError, PsTypeError, PsUndefinedError
from .filters import decode_filters
from .interpreter import PsInterpreter
from .objects import PsArray, PsDict, PsFile, PsMark, PsName, PsOperator, PsProcedure, PsString
from .operators import OperatorRegistry
from .parser import PsParser
from .tokenizer import PsTokenizer


def register_base_operators(registry: OperatorRegistry) -> None:
    """Register core stack, math, dictionary, and control operators."""
    interpreter = PsInterpreter(registry)
    registry.register("pop", lambda ctx: ctx.operand_stack.pop(), min_operands=1)
    registry.register("dup", lambda ctx: ctx.operand_stack.push(ctx.operand_stack.peek()), min_operands=1)
    registry.register("exch", _op_exch, min_operands=2)
    registry.register("clear", lambda ctx: ctx.operand_stack.clear())
    registry.register("copy", _op_copy, min_operands=1)
    registry.register("roll", _op_roll, min_operands=2)
    registry.register("index", _op_index, min_operands=1)
    registry.register("count", lambda ctx: ctx.operand_stack.push(len(ctx.operand_stack)))

    registry.register("add", lambda ctx: _binary_number(ctx, lambda a, b: a + b), min_operands=2)
    registry.register("sub", lambda ctx: _binary_number(ctx, lambda a, b: a - b), min_operands=2)
    registry.register("mul", lambda ctx: _binary_number(ctx, lambda a, b: a * b), min_operands=2)
    registry.register("div", lambda ctx: _binary_number(ctx, lambda a, b: a / b), min_operands=2)
    registry.register("idiv", _op_idiv, min_operands=2)
    registry.register("mod", lambda ctx: _binary_number(ctx, lambda a, b: a % b), min_operands=2)
    registry.register("neg", lambda ctx: ctx.operand_stack.push(-_pop_number(ctx)), min_operands=1)
    registry.register("abs", lambda ctx: ctx.operand_stack.push(abs(_pop_number(ctx))), min_operands=1)
    registry.register("sqrt", lambda ctx: ctx.operand_stack.push(math.sqrt(_pop_number(ctx))), min_operands=1)

    registry.register("sin", lambda ctx: ctx.operand_stack.push(math.sin(math.radians(_pop_number(ctx)))), min_operands=1)
    registry.register("cos", lambda ctx: ctx.operand_stack.push(math.cos(math.radians(_pop_number(ctx)))), min_operands=1)
    registry.register("atan", _op_atan, min_operands=2)

    registry.register("eq", _op_eq, min_operands=2)
    registry.register("ne", _op_ne, min_operands=2)
    registry.register("lt", lambda ctx: _binary_compare(ctx, lambda a, b: a < b), min_operands=2)
    registry.register("gt", lambda ctx: _binary_compare(ctx, lambda a, b: a > b), min_operands=2)
    registry.register("le", lambda ctx: _binary_compare(ctx, lambda a, b: a <= b), min_operands=2)
    registry.register("ge", lambda ctx: _binary_compare(ctx, lambda a, b: a >= b), min_operands=2)
    registry.register("and", _op_and, min_operands=2)
    registry.register("or", _op_or, min_operands=2)
    registry.register("not", _op_not, min_operands=1)
    registry.register("bitshift", _op_bitshift, min_operands=2)

    registry.register("array", _op_array, min_operands=1)
    registry.register("packedarray", _op_packedarray, min_operands=1)
    registry.register("matrix", _op_matrix)
    registry.register("string", _op_string, min_operands=1)
    registry.register("readstring", _op_readstring, min_operands=2)
    registry.register("readhexstring", _op_readhexstring, min_operands=2)
    registry.register("token", _op_token, min_operands=1)
    registry.register("status", _op_status, min_operands=1)
    registry.register("flushfile", _op_flushfile, min_operands=1)
    registry.register("closefile", _op_closefile, min_operands=1)
    registry.register("currentfile", _op_currentfile)
    registry.register("filter", _op_filter, min_operands=2)
    registry.register("length", _op_length, min_operands=1)
    registry.register("get", _op_get, min_operands=2)
    registry.register("put", _op_put, min_operands=3)
    registry.register("getinterval", _op_getinterval, min_operands=3)
    registry.register("putinterval", _op_putinterval, min_operands=3)
    registry.register("aload", _op_aload, min_operands=1)
    registry.register("astore", _op_astore, min_operands=1)

    registry.register("dict", _op_dict, min_operands=1)
    registry.register("<<", _op_dict_mark)
    registry.register(">>", _op_dict_close)
    registry.register("begin", _op_begin, min_operands=1)
    registry.register("end", _op_end)
    registry.register("def", _op_def, min_operands=2)
    registry.register("undef", _op_undef, min_operands=2)
    registry.register("load", lambda ctx: _op_load(ctx, registry), min_operands=1)
    registry.register("currentdict", _op_currentdict)
    registry.register("countdictstack", lambda ctx: ctx.operand_stack.push(len(ctx.dictionary_stack)))
    registry.register("known", _op_known, min_operands=2)

    registry.register("exec", lambda ctx: _op_exec(ctx, interpreter), min_operands=1)
    registry.register("if", lambda ctx: _op_if(ctx, interpreter), min_operands=2)
    registry.register("ifelse", lambda ctx: _op_ifelse(ctx, interpreter), min_operands=3)
    registry.register("repeat", lambda ctx: _op_repeat(ctx, interpreter), min_operands=2)
    registry.register("for", lambda ctx: _op_for(ctx, interpreter), min_operands=4)
    registry.register("forall", lambda ctx: _op_forall(ctx, interpreter), min_operands=2)
    registry.register("loop", lambda ctx: _op_loop(ctx, interpreter), min_operands=1)
    registry.register("exit", _op_exit)
    registry.register("bind", lambda ctx: _op_bind(ctx, registry), min_operands=1)

    registry.register("mark", lambda ctx: ctx.operand_stack.push(PsMark()))
    registry.register("[", lambda ctx: ctx.operand_stack.push(PsMark()))
    registry.register("]", _op_close_mark_array)
    registry.register("cleartomark", _op_cleartomark)
    registry.register("counttomark", _op_counttomark)
    registry.register("cvs", _op_cvs, min_operands=2)
    registry.register("print", _op_print, min_operands=1)
    registry.register("=", _op_print_eq, min_operands=1)
    registry.register("==", _op_print_eq, min_operands=1)
    registry.register("flush", lambda ctx: None)
    registry.register("cvi", _op_cvi, min_operands=1)
    registry.register("cvr", _op_cvr, min_operands=1)
    registry.register("cvn", _op_cvn, min_operands=1)
    registry.register("cvx", _op_cvx, min_operands=1)
    registry.register("xcheck", _op_xcheck, min_operands=1)
    registry.register("stopped", lambda ctx: _op_stopped(ctx, interpreter), min_operands=1)
    registry.register("execform", lambda ctx: _op_execform(ctx, interpreter), min_operands=1)
    registry.register("where", _op_where, min_operands=1)
    registry.register("type", _op_type, min_operands=1)
    registry.register("round", _op_round, min_operands=1)
    registry.register("floor", _op_floor, min_operands=1)
    registry.register("ceiling", _op_ceiling, min_operands=1)
    registry.register("truncate", _op_truncate, min_operands=1)
    registry.register("cvlit", _op_cvlit, min_operands=1)
    registry.register("readonly", _op_readonly, min_operands=1)
    registry.register("findresource", _op_findresource, min_operands=2)
    registry.register("defineresource", _op_defineresource, min_operands=3)
    registry.register("resourcestatus", _op_resourcestatus, min_operands=2)
    registry.register("resourceforall", _op_resourceforall, min_operands=3)
    registry.register("currentpagedevice", _op_currentpagedevice)
    registry.register("setpagedevice", _op_setpagedevice, min_operands=1)
    registry.register("setuserparams", _op_setuserparams, min_operands=1)
    registry.register("currentglobal", _op_currentglobal)
    registry.register("setglobal", _op_setglobal, min_operands=1)
    registry.register("currentpacking", _op_currentpacking)
    registry.register("setpacking", _op_setpacking, min_operands=1)
    registry.register("quit", _op_quit)


def _op_exch(ctx: ExecutionContext) -> None:
    b = ctx.operand_stack.pop()
    a = ctx.operand_stack.pop()
    ctx.operand_stack.push(b)
    ctx.operand_stack.push(a)


def _op_copy(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, (int, float, bool)):
        count = _coerce_int(value)
        if count < 0:
            raise PsRangeError("copy count must be non-negative")
        items = ctx.operand_stack.to_list()
        if count > len(items):
            raise PsRangeError("stack underflow")
        ctx.operand_stack._items.extend(items[-count:])
        return

    destination = value
    source = ctx.operand_stack.pop()
    if isinstance(source, PsArray) and isinstance(destination, PsArray):
        if len(destination.items) < len(source.items):
            raise PsRangeError("copy rangecheck")
        destination.items[: len(source.items)] = list(source.items)
        ctx.operand_stack.push(destination)
        return
    if isinstance(source, PsProcedure) and isinstance(destination, PsProcedure):
        if len(destination.items) < len(source.items):
            raise PsRangeError("copy rangecheck")
        destination.items[: len(source.items)] = list(source.items)
        ctx.operand_stack.push(destination)
        return
    if isinstance(source, PsString) and isinstance(destination, PsString):
        if len(destination.value) < len(source.value):
            raise PsRangeError("copy rangecheck")
        new_value = source.value + destination.value[len(source.value) :]
        object.__setattr__(destination, "value", new_value)
        ctx.operand_stack.push(destination)
        return
    if isinstance(source, PsDict) and isinstance(destination, PsDict):
        destination.items.update(source.items)
        ctx.operand_stack.push(destination)
        return
    raise PsTypeError("copy expects integer or compatible composite objects")


def _op_roll(ctx: ExecutionContext) -> None:
    shift = _pop_int(ctx)
    count = _pop_int(ctx)
    if count <= 0:
        return
    items = ctx.operand_stack.to_list()
    if count > len(items):
        raise PsRangeError("stack underflow")
    shift = shift % count
    if shift == 0:
        return
    tail = items[-count:]
    rotated = tail[-shift:] + tail[:-shift]
    ctx.operand_stack._items[-count:] = rotated


def _op_index(ctx: ExecutionContext) -> None:
    index = _pop_int(ctx)
    if index < 0:
        raise PsRangeError("index must be non-negative")
    items = ctx.operand_stack.to_list()
    if index >= len(items):
        raise PsRangeError("stack underflow")
    ctx.operand_stack.push(items[-(index + 1)])


def _binary_number(ctx: ExecutionContext, fn) -> None:
    b = _pop_number(ctx)
    a = _pop_number(ctx)
    ctx.operand_stack.push(fn(a, b))


def _binary_compare(ctx: ExecutionContext, fn) -> None:
    b = ctx.operand_stack.pop()
    a = ctx.operand_stack.pop()
    ctx.operand_stack.push(fn(a, b))


def _op_idiv(ctx: ExecutionContext) -> None:
    b = _pop_number(ctx)
    a = _pop_number(ctx)
    ctx.operand_stack.push(int(a / b))


def _op_atan(ctx: ExecutionContext) -> None:
    x = _pop_number(ctx)
    y = _pop_number(ctx)
    ctx.operand_stack.push(math.degrees(math.atan2(y, x)))


def _op_eq(ctx: ExecutionContext) -> None:
    b = ctx.operand_stack.pop()
    a = ctx.operand_stack.pop()
    ctx.operand_stack.push(a == b)


def _op_ne(ctx: ExecutionContext) -> None:
    b = ctx.operand_stack.pop()
    a = ctx.operand_stack.pop()
    ctx.operand_stack.push(a != b)


def _op_and(ctx: ExecutionContext) -> None:
    b = ctx.operand_stack.pop()
    a = ctx.operand_stack.pop()
    if isinstance(a, bool) and isinstance(b, bool):
        ctx.operand_stack.push(a and b)
        return
    if isinstance(a, int) and isinstance(b, int):
        ctx.operand_stack.push(a & b)
        return
    raise PsTypeError("and expects bool or int operands")


def _op_or(ctx: ExecutionContext) -> None:
    b = ctx.operand_stack.pop()
    a = ctx.operand_stack.pop()
    if isinstance(a, bool) and isinstance(b, bool):
        ctx.operand_stack.push(a or b)
        return
    if isinstance(a, int) and isinstance(b, int):
        ctx.operand_stack.push(a | b)
        return
    raise PsTypeError("or expects bool or int operands")


def _op_not(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, bool):
        ctx.operand_stack.push(not value)
        return
    if isinstance(value, int):
        ctx.operand_stack.push(~value)
        return
    raise PsTypeError("not expects bool or int operand")


def _op_bitshift(ctx: ExecutionContext) -> None:
    shift = _pop_int(ctx)
    value = _pop_int(ctx)
    if shift >= 0:
        ctx.operand_stack.push(value << shift)
    else:
        ctx.operand_stack.push(value >> (-shift))


def _op_array(ctx: ExecutionContext) -> None:
    size = _pop_int(ctx)
    if size < 0:
        raise PsRangeError("array size must be non-negative")
    ctx.operand_stack.push(PsArray([None] * size))


def _op_packedarray(ctx: ExecutionContext) -> None:
    size = _pop_int(ctx)
    if size < 0:
        raise PsRangeError("packedarray size must be non-negative")
    if size > len(ctx.operand_stack):
        raise PsRangeError("stack underflow")
    items = []
    for _ in range(size):
        items.append(ctx.operand_stack.pop())
    items.reverse()
    ctx.operand_stack.push(PsArray(items))


def _op_matrix(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(PsArray([1.0, 0.0, 0.0, 1.0, 0.0, 0.0]))


def _op_string(ctx: ExecutionContext) -> None:
    size = _pop_int(ctx)
    if size < 0:
        raise PsRangeError("string size must be non-negative")
    ctx.operand_stack.push(PsString(b"\x00" * size))


def _op_currentfile(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(PsFile(name="currentfile", mode=None, data=tuple()))


def _op_filter(ctx: ExecutionContext) -> None:
    filter_obj = ctx.operand_stack.pop()
    params: PsDict | None = None
    source = ctx.operand_stack.pop()
    if isinstance(source, PsDict):
        params = source
        source = ctx.operand_stack.pop()
    if isinstance(filter_obj, PsName):
        filter_name = filter_obj.value
    elif isinstance(filter_obj, str):
        filter_name = filter_obj
    else:
        raise PsTypeError("filter expects name")
    params_dict: dict | None = _filter_params_to_dict(params) if isinstance(params, PsDict) else None
    existing_filters: list[tuple[str, dict | None]] = []
    if isinstance(source, PsFile) and source.name == "currentfile":
        if isinstance(source.data, tuple):
            existing_filters = list(source.data)
    elif isinstance(source, PsName) and source.value == "currentfile":
        pass
    elif isinstance(source, str) and source == "currentfile":
        pass
    else:
        # Unsupported sources are passed through as an empty file wrapper so
        # prologs that bind filter chains continue executing.
        ctx.operand_stack.push(PsFile(name=None, mode=None, data=tuple()))
        return
    existing_filters.append((filter_name, params_dict))
    ctx.operand_stack.push(PsFile(name="currentfile", mode=None, data=tuple(existing_filters)))


def _op_readstring(ctx: ExecutionContext) -> None:
    target = ctx.operand_stack.pop()
    source = ctx.operand_stack.pop()
    if not isinstance(target, PsString):
        raise PsTypeError("readstring expects string")
    count = len(target.value)
    data, remaining_filter, filter_params = _read_from_source(
        ctx,
        source,
        count,
        hex_mode=False,
    )
    complete = len(data) >= count
    if remaining_filter is None:
        if len(data) < count:
            data = data + target.value[len(data) :]
        elif len(data) > count:
            data = data[:count]
    ctx.operand_stack.push(PsString(data, remaining_filter, filter_params))
    ctx.operand_stack.push(complete)


def _op_readhexstring(ctx: ExecutionContext) -> None:
    target = ctx.operand_stack.pop()
    source = ctx.operand_stack.pop()
    if not isinstance(target, PsString):
        raise PsTypeError("readhexstring expects string")
    count = len(target.value)
    data, remaining_filter, filter_params = _read_from_source(
        ctx,
        source,
        count,
        hex_mode=True,
    )
    complete = len(data) >= count
    if remaining_filter is None:
        if len(data) < count:
            data = data + target.value[len(data) :]
        elif len(data) > count:
            data = data[:count]
    ctx.operand_stack.push(PsString(data, remaining_filter, filter_params))
    ctx.operand_stack.push(complete)


def _op_token(ctx: ExecutionContext) -> None:
    source = ctx.operand_stack.pop()
    if not isinstance(source, PsFile) or source.name != "currentfile":
        ctx.operand_stack.push(False)
        return
    tokenizer = ctx.systemdict.items.get("__tokenizer__")
    if not isinstance(tokenizer, PsTokenizer):
        ctx.operand_stack.push(False)
        return
    parser = PsParser(tokenizer)
    obj = parser.parse_object()
    if obj is None:
        ctx.operand_stack.push(False)
        return
    ctx.operand_stack.push(obj)
    ctx.operand_stack.push(True)


def _op_status(ctx: ExecutionContext) -> None:
    _ = ctx.operand_stack.pop()
    ctx.operand_stack.push(False)


def _op_flushfile(ctx: ExecutionContext) -> None:
    _ = ctx.operand_stack.pop()


def _op_closefile(ctx: ExecutionContext) -> None:
    _ = ctx.operand_stack.pop()


def _op_length(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsArray):
        ctx.operand_stack.push(len(value.items))
        return
    if isinstance(value, PsProcedure):
        ctx.operand_stack.push(len(value.items))
        return
    if isinstance(value, PsDict):
        ctx.operand_stack.push(len(value.items))
        return
    if isinstance(value, PsString):
        ctx.operand_stack.push(len(value.value))
        return
    if isinstance(value, PsName):
        ctx.operand_stack.push(len(value.value))
        return
    if isinstance(value, str):
        ctx.operand_stack.push(len(value))
        return
    raise PsTypeError("length expects array, dict, or string")


def _op_get(ctx: ExecutionContext) -> None:
    key = ctx.operand_stack.pop()
    container = ctx.operand_stack.pop()
    if isinstance(container, PsArray):
        index = _coerce_int(key)
        if index < 0 or index >= len(container.items):
            raise PsRangeError("get rangecheck")
        ctx.operand_stack.push(container.items[index])
        return
    if isinstance(container, PsProcedure):
        index = _coerce_int(key)
        if index < 0 or index >= len(container.items):
            raise PsRangeError("get rangecheck")
        ctx.operand_stack.push(container.items[index])
        return
    if isinstance(container, PsString):
        index = _coerce_int(key)
        if index < 0 or index >= len(container.value):
            raise PsRangeError("get rangecheck")
        ctx.operand_stack.push(container.value[index])
        return
    if isinstance(container, PsDict):
        name = _coerce_key(key)
        if name not in container.items:
            raise PsUndefinedError(f"undefined key {name}")
        ctx.operand_stack.push(container.items[name])
        return
    raise PsTypeError("get expects array, dict, or string")


def _op_put(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    key = ctx.operand_stack.pop()
    container = ctx.operand_stack.pop()
    if isinstance(container, PsArray):
        index = _coerce_int(key)
        if index < 0 or index >= len(container.items):
            raise PsRangeError("put rangecheck")
        container.items[index] = value
        return
    if isinstance(container, PsProcedure):
        index = _coerce_int(key)
        if index < 0 or index >= len(container.items):
            raise PsRangeError("put rangecheck")
        container.items[index] = value
        return
    if isinstance(container, PsString):
        index = _coerce_int(key)
        if index < 0 or index >= len(container.value):
            raise PsRangeError("put rangecheck")
        try:
            byte_value = _coerce_int(value)
        except PsTypeError as exc:
            raise PsTypeError("put expects int for string") from exc
        if byte_value < 0 or byte_value > 255:
            raise PsRangeError("put expects value in 0..255 for string")
        new_value = (
            container.value[:index]
            + bytes([byte_value])
            + container.value[index + 1 :]
        )
        object.__setattr__(container, "value", new_value)
        return
    if isinstance(container, PsDict):
        name = _coerce_key(key)
        container.items[name] = value
        return
    raise PsTypeError("put expects array, procedure, dict, or string")


def _op_getinterval(ctx: ExecutionContext) -> None:
    count = _pop_int(ctx)
    index = _pop_int(ctx)
    container = ctx.operand_stack.pop()
    if count < 0 or index < 0:
        raise PsRangeError("getinterval expects non-negative index and count")
    if isinstance(container, PsArray):
        if index + count > len(container.items):
            raise PsRangeError("getinterval rangecheck")
        ctx.operand_stack.push(PsArray(container.items[index : index + count]))
        return
    if isinstance(container, PsProcedure):
        if index + count > len(container.items):
            raise PsRangeError("getinterval rangecheck")
        ctx.operand_stack.push(PsProcedure(container.items[index : index + count]))
        return
    if isinstance(container, PsString):
        if index + count > len(container.value):
            raise PsRangeError("getinterval rangecheck")
        ctx.operand_stack.push(PsString(container.value[index : index + count]))
        return
    raise PsTypeError("getinterval expects array or string")


def _op_putinterval(ctx: ExecutionContext) -> None:
    source = ctx.operand_stack.pop()
    index = _pop_int(ctx)
    container = ctx.operand_stack.pop()
    if index < 0:
        raise PsRangeError("putinterval expects non-negative index")
    if isinstance(container, PsArray):
        source_items = _coerce_array_like_items(source)
        end = index + len(source_items)
        if end > len(container.items):
            raise PsRangeError("putinterval rangecheck")
        container.items[index:end] = source_items
        return
    if isinstance(container, PsProcedure):
        source_items = _coerce_array_like_items(source)
        end = index + len(source_items)
        if end > len(container.items):
            raise PsRangeError("putinterval rangecheck")
        container.items[index:end] = source_items
        return
    if isinstance(container, PsString):
        if isinstance(source, PsString):
            source_bytes = source.value
        elif isinstance(source, str):
            source_bytes = source.encode("latin-1", errors="replace")
        else:
            raise PsTypeError("putinterval expects string source")
        end = index + len(source_bytes)
        if end > len(container.value):
            raise PsRangeError("putinterval rangecheck")
        new_value = container.value[:index] + source_bytes + container.value[end:]
        object.__setattr__(container, "value", new_value)
        return
    raise PsTypeError("putinterval expects array or string")


def _op_aload(ctx: ExecutionContext) -> None:
    array = ctx.operand_stack.pop()
    if not isinstance(array, PsArray):
        if not isinstance(array, PsProcedure):
            raise PsTypeError("aload expects array")
        items = array.items
    else:
        items = array.items
    for item in items:
        ctx.operand_stack.push(item)
    ctx.operand_stack.push(array)


def _op_astore(ctx: ExecutionContext) -> None:
    array = ctx.operand_stack.pop()
    if not isinstance(array, PsArray):
        if not isinstance(array, PsProcedure):
            raise PsTypeError("astore expects array")
    for index in range(len(array.items) - 1, -1, -1):
        array.items[index] = ctx.operand_stack.pop()
    ctx.operand_stack.push(array)


def _coerce_array_like_items(value: object) -> list[object]:
    if isinstance(value, PsArray):
        return value.items
    if isinstance(value, PsProcedure):
        return value.items
    raise PsTypeError("putinterval expects array source")


def _op_dict(ctx: ExecutionContext) -> None:
    _ = _pop_int(ctx)
    ctx.operand_stack.push(PsDict({}))


def _op_dict_mark(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(PsMark(kind="dictmark"))


def _op_dict_close(ctx: ExecutionContext) -> None:
    items: list[object] = []
    while len(ctx.operand_stack) > 0:
        value = ctx.operand_stack.pop()
        if isinstance(value, PsMark) and value.kind == "dictmark":
            break
        items.append(value)
    else:
        raise PsRangeError(">> without <<")
    items.reverse()
    if len(items) % 2 != 0:
        raise PsRangeError("dict stack mismatch")
    mapping: dict[object, object] = {}
    for idx in range(0, len(items), 2):
        key_obj = items[idx]
        value = items[idx + 1]
        key = _coerce_key(key_obj)
        mapping[key] = value
    ctx.operand_stack.push(PsDict(mapping))


def _op_begin(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if not isinstance(value, PsDict):
        raise PsTypeError("begin expects dictionary")
    ctx.dictionary_stack.push(value)


def _op_end(ctx: ExecutionContext) -> None:
    ctx.dictionary_stack.pop()


def _op_def(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    key = ctx.operand_stack.pop()
    if not isinstance(key, PsName) and isinstance(value, PsProcedure) and value.items:
        head = value.items[0]
        if isinstance(head, PsName) and head.literal:
            key = head
            value = PsProcedure(list(value.items[1:]))
    name = _coerce_key(key)
    ctx.dictionary_stack.peek().items[name] = value


def _op_undef(ctx: ExecutionContext) -> None:
    key = _coerce_key(ctx.operand_stack.pop())
    dictionary = ctx.operand_stack.pop()
    if not isinstance(dictionary, PsDict):
        raise PsTypeError("undef expects dictionary")
    dictionary.items.pop(key, None)


def _op_load(ctx: ExecutionContext, registry: OperatorRegistry) -> None:
    key = ctx.operand_stack.pop()
    if isinstance(key, PsName):
        name = key.value
    elif isinstance(key, str):
        name = key
    else:
        raise PsTypeError("load expects name")
    for mapping in reversed(ctx.dictionary_stack._items):
        if name in mapping.items:
            ctx.operand_stack.push(mapping.items[name])
            return
    if registry.get(name) is not None:
        ctx.operand_stack.push(PsOperator(name))
        return
    raise PsUndefinedError(f"undefined name {name}")


def _op_currentdict(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(ctx.dictionary_stack.peek())


def _op_known(ctx: ExecutionContext) -> None:
    key = _coerce_key(ctx.operand_stack.pop())
    dictionary = ctx.operand_stack.pop()
    if not isinstance(dictionary, PsDict):
        raise PsTypeError("known expects dictionary")
    ctx.operand_stack.push(key in dictionary.items)


def _op_exec(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsProcedure):
        interpreter.execute_procedure(value, ctx)
        return
    if isinstance(value, PsName):
        interpreter._execute_name(value.value, ctx)  # type: ignore[attr-defined]
        return
    if isinstance(value, PsOperator):
        interpreter._execute_name(value.name, ctx)  # type: ignore[attr-defined]
        return
    if isinstance(value, str):
        interpreter._execute_name(value, ctx)  # type: ignore[attr-defined]
        return
    raise PsTypeError("exec expects procedure")


def _op_stopped(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    value = ctx.operand_stack.pop()
    try:
        if isinstance(value, PsProcedure):
            interpreter.execute_procedure(value, ctx)
        elif isinstance(value, PsName):
            interpreter._execute_name(value.value, ctx)  # type: ignore[attr-defined]
        elif isinstance(value, PsOperator):
            interpreter._execute_name(value.name, ctx)  # type: ignore[attr-defined]
        elif isinstance(value, str):
            interpreter._execute_name(value, ctx)  # type: ignore[attr-defined]
        else:
            raise PsTypeError("stopped expects executable object")
    except PsError:
        ctx.operand_stack.push(True)
        return
    ctx.operand_stack.push(False)


def _op_execform(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    form = ctx.operand_stack.pop()
    if not isinstance(form, PsDict):
        return
    paint_proc = form.items.get("PaintProc")
    if isinstance(paint_proc, PsProcedure):
        interpreter.execute_procedure(paint_proc, ctx)


def _op_if(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    proc = ctx.operand_stack.pop()
    condition = _pop_bool(ctx)
    if condition:
        if not isinstance(proc, PsProcedure):
            raise PsTypeError("if expects procedure")
        interpreter.execute_procedure(proc, ctx)


def _op_ifelse(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    proc_false = ctx.operand_stack.pop()
    proc_true = ctx.operand_stack.pop()
    condition = _pop_bool(ctx)
    proc = proc_true if condition else proc_false
    if not isinstance(proc, PsProcedure):
        raise PsTypeError("ifelse expects procedure")
    interpreter.execute_procedure(proc, ctx)


def _op_repeat(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    proc = ctx.operand_stack.pop()
    count = _pop_int(ctx)
    if not isinstance(proc, PsProcedure):
        raise PsTypeError("repeat expects procedure")
    for _ in range(count):
        interpreter.execute_procedure(proc, ctx)


def _op_for(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    proc = ctx.operand_stack.pop()
    limit = _pop_number(ctx)
    increment = _pop_number(ctx)
    initial = _pop_number(ctx)
    if not isinstance(proc, PsProcedure):
        raise PsTypeError("for expects procedure")
    if increment == 0:
        return
    value = initial
    if increment > 0:
        cond = lambda v: v <= limit + 1e-9
    else:
        cond = lambda v: v >= limit - 1e-9
    while cond(value):
        ctx.operand_stack.push(value)
        interpreter.execute_procedure(proc, ctx)
        value += increment


def _op_forall(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    proc = ctx.operand_stack.pop()
    container = ctx.operand_stack.pop()
    if not isinstance(proc, PsProcedure):
        raise PsTypeError("forall expects procedure")
    if isinstance(container, PsArray):
        for item in container.items:
            ctx.operand_stack.push(item)
            interpreter.execute_procedure(proc, ctx)
        return
    if isinstance(container, PsString):
        for byte in container.value:
            ctx.operand_stack.push(int(byte))
            interpreter.execute_procedure(proc, ctx)
        return
    if isinstance(container, PsDict):
        for key, value in container.items.items():
            if isinstance(key, str):
                ctx.operand_stack.push(PsName(key, literal=True))
            else:
                ctx.operand_stack.push(key)
            ctx.operand_stack.push(value)
            interpreter.execute_procedure(proc, ctx)
        return
    raise PsTypeError("forall expects array, dict, or string")


class _PsLoopExit(Exception):
    pass


def _op_loop(ctx: ExecutionContext, interpreter: PsInterpreter) -> None:
    proc = ctx.operand_stack.pop()
    if not isinstance(proc, PsProcedure):
        raise PsTypeError("loop expects procedure")
    while True:
        try:
            interpreter.execute_procedure(proc, ctx)
        except _PsLoopExit:
            break


def _op_exit(ctx: ExecutionContext) -> None:
    raise _PsLoopExit()


def _op_bind(ctx: ExecutionContext, registry: OperatorRegistry) -> None:
    proc = ctx.operand_stack.pop()
    if not isinstance(proc, PsProcedure):
        raise PsTypeError("bind expects procedure")
    _bind_procedure(proc, ctx, registry)
    ctx.operand_stack.push(proc)


def _bind_procedure(proc: PsProcedure, ctx: ExecutionContext, registry: OperatorRegistry) -> None:
    bound: list[object] = []
    for item in proc.items:
        if isinstance(item, PsProcedure):
            _bind_procedure(item, ctx, registry)
            bound.append(item)
            continue
        if isinstance(item, PsName) and not item.literal:
            replacement = _bind_lookup(item.value, ctx, registry)
            if replacement is not None:
                bound.append(replacement)
                continue
        bound.append(item)
    proc.items = bound


def _bind_lookup(name: str, ctx: ExecutionContext, registry: OperatorRegistry) -> PsOperator | None:
    for mapping in reversed(ctx.dictionary_stack._items):
        if name in mapping.items:
            value = mapping.items[name]
            if isinstance(value, PsOperator):
                return value
            return None
    if registry.get(name) is not None:
        return PsOperator(name)
    return None


def _op_cleartomark(ctx: ExecutionContext) -> None:
    while True:
        item = ctx.operand_stack.pop()
        if isinstance(item, PsMark):
            return


def _op_counttomark(ctx: ExecutionContext) -> None:
    count = 0
    for item in reversed(ctx.operand_stack.to_list()):
        if isinstance(item, PsMark):
            ctx.operand_stack.push(count)
            return
        count += 1
    raise PsRangeError("unmatched mark")


def _op_close_mark_array(ctx: ExecutionContext) -> None:
    items: list[object] = []
    while len(ctx.operand_stack) > 0:
        item = ctx.operand_stack.pop()
        if isinstance(item, PsMark) and item.kind == "mark":
            items.reverse()
            ctx.operand_stack.push(PsArray(items))
            return
        items.append(item)
    raise PsRangeError("] without mark")


def _op_cvs(ctx: ExecutionContext) -> None:
    container = ctx.operand_stack.pop()
    value = ctx.operand_stack.pop()
    if not isinstance(container, PsString):
        raise PsTypeError("cvs expects string")
    encoded = _format_ps_value(value).encode("ascii", errors="replace")
    if len(encoded) > len(container.value):
        raise PsRangeError("string too small for cvs")
    ctx.operand_stack.push(PsString(encoded))


def _op_print(ctx: ExecutionContext) -> None:
    _ = ctx.operand_stack.pop()


def _op_print_eq(ctx: ExecutionContext) -> None:
    _ = ctx.operand_stack.pop()


def _op_cvi(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, bool):
        ctx.operand_stack.push(int(value))
        return
    if isinstance(value, (int, float)):
        ctx.operand_stack.push(int(value))
        return
    if isinstance(value, PsString):
        text = value.value.decode("latin-1", errors="ignore").strip()
        try:
            ctx.operand_stack.push(int(float(text)))
            return
        except ValueError as exc:
            raise PsTypeError("cvi expects numeric string") from exc
    raise PsTypeError("cvi expects number or string")


def _op_cvr(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, (int, float, bool)):
        ctx.operand_stack.push(float(value))
        return
    if isinstance(value, PsString):
        text = value.value.decode("latin-1", errors="ignore").strip()
        try:
            ctx.operand_stack.push(float(text))
            return
        except ValueError as exc:
            raise PsTypeError("cvr expects numeric string") from exc
    raise PsTypeError("cvr expects number or string")


def _op_cvn(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if not isinstance(value, PsString):
        raise PsTypeError("cvn expects string")
    name = value.value.decode("latin-1", errors="replace")
    ctx.operand_stack.push(PsName(name, literal=True))


def _op_cvx(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsName):
        ctx.operand_stack.push(PsName(value.value, literal=False))
        return
    if isinstance(value, PsArray):
        ctx.operand_stack.push(PsProcedure(list(value.items)))
        return
    ctx.operand_stack.push(value)


def _op_xcheck(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    executable = isinstance(value, (PsProcedure, PsOperator)) or (
        isinstance(value, PsName) and not value.literal
    )
    ctx.operand_stack.push(executable)


def _op_where(ctx: ExecutionContext) -> None:
    key = ctx.operand_stack.pop()
    name = _coerce_key(key)
    for mapping in reversed(ctx.dictionary_stack._items):
        if name in mapping.items:
            ctx.operand_stack.push(mapping)
            ctx.operand_stack.push(True)
            return
    ctx.operand_stack.push(False)


def _op_type(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsArray):
        t = "arraytype"
    elif isinstance(value, PsDict):
        t = "dicttype"
    elif isinstance(value, PsString):
        t = "stringtype"
    elif isinstance(value, PsProcedure):
        t = "arraytype"
    elif isinstance(value, PsName):
        t = "nametype"
    elif isinstance(value, PsOperator):
        t = "operatortype"
    elif isinstance(value, bool):
        t = "booleantype"
    elif isinstance(value, int):
        t = "integertype"
    elif isinstance(value, float):
        t = "realtype"
    elif value is None:
        t = "nulltype"
    else:
        t = "unknowntype"
    ctx.operand_stack.push(PsName(t, literal=True))


def _op_round(ctx: ExecutionContext) -> None:
    value = _pop_number(ctx)
    ctx.operand_stack.push(int(round(value)))


def _op_floor(ctx: ExecutionContext) -> None:
    value = _pop_number(ctx)
    ctx.operand_stack.push(int(math.floor(value)))


def _op_ceiling(ctx: ExecutionContext) -> None:
    value = _pop_number(ctx)
    ctx.operand_stack.push(int(math.ceil(value)))


def _op_truncate(ctx: ExecutionContext) -> None:
    value = _pop_number(ctx)
    ctx.operand_stack.push(int(value))


def _op_cvlit(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsName):
        ctx.operand_stack.push(PsName(value.value, literal=True))
        return
    ctx.operand_stack.push(value)


def _op_readonly(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    ctx.operand_stack.push(value)


def _op_findresource(ctx: ExecutionContext) -> None:
    category = _coerce_key(ctx.operand_stack.pop())
    key = _coerce_key(ctx.operand_stack.pop())
    resources = _resource_store(ctx)
    category_dict = resources.get(category)
    if isinstance(category_dict, PsDict) and key in category_dict.items:
        ctx.operand_stack.push(category_dict.items[key])
        return
    # Keep execution moving even when optional resources are unavailable.
    ctx.operand_stack.push(PsDict({}))


def _op_defineresource(ctx: ExecutionContext) -> None:
    category = _coerce_key(ctx.operand_stack.pop())
    instance = ctx.operand_stack.pop()
    key = _coerce_key(ctx.operand_stack.pop())
    resources = _resource_store(ctx)
    category_dict = resources.get(category)
    if not isinstance(category_dict, PsDict):
        category_dict = PsDict({})
        resources[category] = category_dict
    category_dict.items[key] = instance
    ctx.operand_stack.push(instance)


def _op_resourcestatus(ctx: ExecutionContext) -> None:
    category = _coerce_key(ctx.operand_stack.pop())
    key = _coerce_key(ctx.operand_stack.pop())
    resources = _resource_store(ctx)
    category_dict = resources.get(category)
    if isinstance(category_dict, PsDict) and key in category_dict.items:
        ctx.operand_stack.push(0)
        ctx.operand_stack.push(0)
        ctx.operand_stack.push(True)
        return
    ctx.operand_stack.push(False)


def _op_resourceforall(ctx: ExecutionContext) -> None:
    proc = ctx.operand_stack.pop()
    _template = ctx.operand_stack.pop()
    _category = ctx.operand_stack.pop()
    if not isinstance(proc, PsProcedure):
        raise PsTypeError("resourceforall expects procedure")


def _op_currentpagedevice(ctx: ExecutionContext) -> None:
    pagedevice = ctx.systemdict.items.get("pagedevice")
    if isinstance(pagedevice, PsDict):
        ctx.operand_stack.push(pagedevice)
    else:
        ctx.operand_stack.push(PsDict({}))


def _op_setpagedevice(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if isinstance(value, PsDict):
        ctx.systemdict.items["pagedevice"] = value


def _op_setuserparams(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    if not isinstance(value, PsDict):
        raise PsTypeError("setuserparams expects dictionary")
    params = ctx.systemdict.items.get("__userparams__")
    if not isinstance(params, PsDict):
        params = PsDict({})
        ctx.systemdict.items["__userparams__"] = params
    params.items.update(value.items)


def _op_currentglobal(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(bool(ctx.systemdict.items.get("__currentglobal__", False)))


def _op_setglobal(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    ctx.systemdict.items["__currentglobal__"] = bool(value)


def _op_currentpacking(ctx: ExecutionContext) -> None:
    ctx.operand_stack.push(bool(ctx.systemdict.items.get("__currentpacking__", False)))


def _op_setpacking(ctx: ExecutionContext) -> None:
    value = ctx.operand_stack.pop()
    ctx.systemdict.items["__currentpacking__"] = bool(value)


def _op_quit(ctx: ExecutionContext) -> None:
    raise PsQuit()


def _read_from_source(
    ctx: ExecutionContext,
    source: object,
    count: int,
    *,
    hex_mode: bool,
) -> tuple[bytes, str | None, dict | None]:
    tokenizer = ctx.systemdict.items.get("__tokenizer__")
    if not isinstance(tokenizer, PsTokenizer):
        return b"", None, None
    filters: list[tuple[str, dict | None]] = []
    if isinstance(source, PsFile) and source.name == "currentfile":
        if isinstance(source.data, tuple):
            filters = list(source.data)
    elif isinstance(source, PsName) and source.value == "currentfile":
        filters = []
    elif isinstance(source, str) and source == "currentfile":
        filters = []
    else:
        return b"", None, None

    if hex_mode and not filters:
        decoded, _ = tokenizer.read_asciihex_decoded(count)
        return decoded, None, None

    if not filters:
        return tokenizer.read_raw(count), None, None

    first_filter = _normalize_filter_name(filters[0][0])
    if first_filter == "ASCIIHexDecode":
        encoded = (
            tokenizer.read_asciihex_source(count)
            if count > 0
            else tokenizer.read_until_asciihex_eod()
        )
    elif first_filter == "ASCII85Decode":
        encoded = tokenizer.read_until_ascii85_eod()
    else:
        encoded = tokenizer.read_raw(count)
    decoded = decode_filters(encoded, filters, allow_encoded=True)
    return decoded.data, decoded.remaining_filter, decoded.params


def _normalize_filter_name(name: str) -> str:
    return name[1:] if name.startswith("/") else name


def _filter_params_to_dict(value: PsDict | None) -> dict | None:
    if value is None:
        return None
    result: dict = {}
    for key, raw in value.items.items():
        result[key] = _to_python_filter_param(raw)
    return result


def _to_python_filter_param(value: object) -> object:
    if isinstance(value, PsName):
        return value.value
    if isinstance(value, PsString):
        return value.value
    if isinstance(value, PsArray):
        return [_to_python_filter_param(item) for item in value.items]
    if isinstance(value, PsDict):
        return {k: _to_python_filter_param(v) for k, v in value.items.items()}
    return value


def _pop_number(ctx: ExecutionContext) -> float:
    value = ctx.operand_stack.pop()
    if isinstance(value, (int, float)):
        return float(value)
    raise PsTypeError("number expected")


def _pop_int(ctx: ExecutionContext) -> int:
    return _coerce_int(ctx.operand_stack.pop())


def _coerce_int(value: object) -> int:
    if isinstance(value, PsName):
        value = value.value
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        radix = _parse_radix_integer_text(text)
        if radix is not None:
            return radix
        try:
            return int(text, 10)
        except ValueError as exc:
            raise PsTypeError("integer expected") from exc
    raise PsTypeError("integer expected")


def _coerce_key(value: object) -> object:
    if isinstance(value, PsName):
        return value.value
    if isinstance(value, PsOperator):
        return value.name
    if isinstance(value, PsString):
        return value.value.decode("latin-1", errors="replace")
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    raise PsTypeError("key expected")


def _pop_bool(ctx: ExecutionContext) -> bool:
    value = ctx.operand_stack.pop()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    raise PsTypeError("boolean expected")


def _format_ps_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if abs(value) <= 1e-6:
            return "0"
        if float(int(value)) == float(value):
            return str(int(value))
        text = f"{value:.6g}"
        if "e" in text or "E" in text:
            text = f"{value:.6f}"
        return text.rstrip("0").rstrip(".")
    if isinstance(value, PsName):
        return value.value
    if isinstance(value, PsString):
        return value.value.decode("latin-1", errors="replace")
    return str(value)


def _parse_radix_integer_text(text: str) -> int | None:
    sign = 1
    body = text
    if body.startswith("+"):
        body = body[1:]
    elif body.startswith("-"):
        sign = -1
        body = body[1:]
    if "#" not in body:
        return None
    base_text, number_text = body.split("#", 1)
    if not base_text or not number_text:
        return None
    try:
        base = int(base_text, 10)
    except ValueError:
        return None
    if base < 2 or base > 36:
        return None
    try:
        return sign * int(number_text, base)
    except ValueError:
        return None


def _resource_store(ctx: ExecutionContext) -> dict[str, PsDict]:
    value = ctx.systemdict.items.get("__resources__")
    if isinstance(value, dict):
        return value
    resources: dict[str, PsDict] = {}
    ctx.systemdict.items["__resources__"] = resources
    return resources
