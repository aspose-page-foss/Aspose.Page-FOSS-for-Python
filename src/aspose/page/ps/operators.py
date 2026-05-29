"""Operator registry and dispatch helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .context import ExecutionContext


@dataclass
class OperatorEntry:
    """Descriptor for a registered PostScript operator."""

    name: str
    min_operands: int
    max_operands: int | None
    fn: Callable[[ExecutionContext], None]


class OperatorRegistry:
    """Register and resolve PostScript operator implementations.

    Example:
        >>> registry = OperatorRegistry()
        >>> registry.register("noop", lambda ctx: None)
        >>> registry.get("noop").name
        'noop'
    """

    def __init__(self) -> None:
        self._operators: dict[str, OperatorEntry] = {}

    def register(
        self,
        name: str,
        fn: Callable[[ExecutionContext], None],
        min_operands: int = 0,
        max_operands: int | None = None,
    ) -> None:
        """Register an operator implementation.

        Example:
            >>> registry = OperatorRegistry()
            >>> registry.register("pop", lambda ctx: ctx.operand_stack.pop(), min_operands=1)
        """
        self._operators[name] = OperatorEntry(
            name=name,
            min_operands=min_operands,
            max_operands=max_operands,
            fn=fn,
        )

    def get(self, name: str) -> OperatorEntry | None:
        """Lookup a registered operator entry by name.

        Example:
            >>> registry = OperatorRegistry()
            >>> registry.get("missing") is None
            True
        """
        return self._operators.get(name)
