"""PostScript/EPS interpreter."""

from __future__ import annotations

import os
import time

from .context import ExecutionContext
from .dsc import parse_dsc_comments
from .errors import PsError, PsQuit, PsRangeError, PsUndefinedError
from .objects import PsName, PsOperator, PsProcedure, PsObject
from .operators import OperatorRegistry
from .parser import PsParser
from .tokenizer import PsTokenizer

_MISSING = object()


class PsInterpreter:
    """Execute PostScript/EPS objects using a registry of operators.

    Example:
        >>> registry = OperatorRegistry()
        >>> interpreter = PsInterpreter(registry)
        >>> ctx = ExecutionContext(
        ...     operand_stack=PsStack(),
        ...     execution_stack=PsStack(),
        ...     dictionary_stack=PsStack(),
        ...     graphics_state_stack=PsStack(),
        ...     userdict=PsDict(),
        ...     systemdict=PsDict(),
        ... )
        >>> interpreter.execute(b"%!PS\\n", ctx)
    """

    def __init__(self, operators: OperatorRegistry) -> None:
        self._operators = operators
        self._trace_every = self._parse_int_env("PS_TRACE_EVERY")
        self._max_steps = self._parse_int_env("PS_MAX_STEPS")
        self._trace_ops = os.getenv("PS_TRACE_OPS") == "1"
        self._trace_slow_ms = self._parse_int_env("PS_TRACE_SLOW_MS")
        self._step_counter = 0
        self._last_op: str | None = None
        self._last_obj: str | None = None

    @staticmethod
    def _parse_int_env(name: str) -> int:
        raw = os.getenv(name)
        if not raw:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    def execute(self, data: bytes, ctx: ExecutionContext) -> None:
        """Parse and execute a PostScript/EPS byte stream.

        Example:
            >>> interpreter = PsInterpreter(OperatorRegistry())
            >>> ctx = ExecutionContext(
            ...     operand_stack=PsStack(),
            ...     execution_stack=PsStack(),
            ...     dictionary_stack=PsStack(),
            ...     graphics_state_stack=PsStack(),
            ...     userdict=PsDict(),
            ...     systemdict=PsDict(),
            ... )
            >>> interpreter.execute(b"%!PS\\n", ctx)
        """
        self._step_counter = 0
        self._last_op = None
        self._last_obj = None
        ctx.dsc = parse_dsc_comments(data)
        tokenizer = PsTokenizer(data)
        parser = PsParser(tokenizer)
        previous_tokenizer = ctx.systemdict.items.get("__tokenizer__")
        ctx.systemdict.items["__tokenizer__"] = tokenizer
        try:
            while True:
                obj = parser.parse_object()
                if obj is None:
                    break
                self.execute_object(obj, ctx)
        except PsQuit:
            return
        finally:
            if previous_tokenizer is None:
                ctx.systemdict.items.pop("__tokenizer__", None)
            else:
                ctx.systemdict.items["__tokenizer__"] = previous_tokenizer

    def execute_objects(self, objects: list[PsObject], ctx: ExecutionContext) -> None:
        """Execute a sequence of already-parsed objects."""
        for obj in objects:
            self.execute_object(obj, ctx)

    def execute_object(self, obj: PsObject, ctx: ExecutionContext) -> None:
        """Execute a single object."""
        try:
            self._tick(obj, ctx)
            if isinstance(obj, PsName):
                if obj.literal:
                    ctx.operand_stack.push(obj)
                    return
                self._execute_name(obj.value, ctx)
                return
            if isinstance(obj, PsOperator):
                self._execute_name(obj.name, ctx)
                return
            ctx.operand_stack.push(obj)
        except PsError as exc:
            if ctx.error_handler is not None:
                ctx.error_handler(exc)
                return
            raise

    def execute_procedure(self, proc: PsProcedure, ctx: ExecutionContext) -> None:
        """Execute a procedure explicitly."""
        for item in proc.items:
            self.execute_object(item, ctx)

    def _execute_name(self, name: str, ctx: ExecutionContext) -> None:
        self._last_op = name
        if self._trace_ops:
            print(f"PS TRACE op start: {name}", flush=True)
        start = time.perf_counter()
        entry = self._operators.get(name)
        if entry is not None:
            if len(ctx.operand_stack) < entry.min_operands:
                raise PsRangeError(f"stack underflow for operator {name}")
            entry.fn(ctx)
            self._trace_slow_op(name, start)
            return
        value = self._lookup_dict(name, ctx)
        if value is _MISSING:
            raise PsUndefinedError(f"undefined name {name}")
        if isinstance(value, PsProcedure):
            self.execute_procedure(value, ctx)
            self._trace_slow_op(name, start)
            return
        if isinstance(value, PsOperator):
            # Values defined via patterns like `/m /moveto load def` must
            # execute when referenced by executable names.
            self._execute_name(value.name, ctx)
            self._trace_slow_op(name, start)
            return
        ctx.operand_stack.push(value)
        self._trace_slow_op(name, start)

    def _trace_slow_op(self, name: str, start: float) -> None:
        if not self._trace_slow_ms:
            return
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if elapsed_ms >= self._trace_slow_ms:
            print(f"PS TRACE op slow: {name} {elapsed_ms:.1f}ms", flush=True)

    def _tick(self, obj: PsObject, ctx: ExecutionContext) -> None:
        self._step_counter += 1
        if self._max_steps and self._step_counter > self._max_steps:
            raise PsError("execution step limit exceeded")
        if not self._trace_every:
            return
        if self._step_counter % self._trace_every != 0:
            return
        self._last_obj = self._describe_obj(obj)
        print(
            "PS TRACE step="
            f"{self._step_counter} "
            f"obj={self._last_obj} "
            f"last_op={self._last_op} "
            f"op_stack={len(ctx.operand_stack)} "
            f"dict_stack={len(ctx.dictionary_stack)} "
            f"gs_stack={len(ctx.graphics_state_stack)}",
            flush=True,
        )

    @staticmethod
    def _describe_obj(obj: PsObject) -> str:
        if isinstance(obj, PsName):
            if obj.literal:
                return f"/{obj.value}"
            return obj.value
        if isinstance(obj, PsOperator):
            return obj.name
        return obj.__class__.__name__

    @staticmethod
    def _lookup_dict(name: str, ctx: ExecutionContext) -> PsObject | object:
        for mapping in reversed(ctx.dictionary_stack._items):
            if name in mapping.items:
                return mapping.items[name]
        return _MISSING
