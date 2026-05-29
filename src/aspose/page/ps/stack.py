"""PostScript stack helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, List, TypeVar

from .errors import PsRangeError

T = TypeVar("T")


@dataclass
class PsStack(Generic[T]):
    """Simple stack implementation for PostScript execution.

    Example:
        >>> stack = PsStack[int]()
        >>> stack.push(1)
        >>> stack.pop()
        1
    """

    _items: List[T] = field(default_factory=list)

    def push(self, item: T) -> None:
        """Push an item onto the stack.

        Example:
            >>> stack = PsStack[int]()
            >>> stack.push(2)
        """
        self._items.append(item)

    def pop(self) -> T:
        """Pop the top item from the stack.

        Example:
            >>> stack = PsStack([1, 2])
            >>> stack.pop()
            2
        """
        if not self._items:
            raise PsRangeError("stack underflow")
        return self._items.pop()

    def peek(self) -> T:
        """Peek at the top item without removing it.

        Example:
            >>> stack = PsStack([1])
            >>> stack.peek()
            1
        """
        if not self._items:
            raise PsRangeError("stack underflow")
        return self._items[-1]

    def clear(self) -> None:
        self._items.clear()

    def clone(self) -> "PsStack[T]":
        return PsStack(self._items.copy())

    def to_list(self) -> list[T]:
        """Return a shallow list copy of stack items.

        Example:
            >>> stack = PsStack([1, 2])
            >>> stack.to_list()
            [1, 2]
        """
        return self._items.copy()

    def __len__(self) -> int:
        return len(self._items)
