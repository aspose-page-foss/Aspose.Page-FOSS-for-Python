"""XPS resource dictionaries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class XpsResourceDictionary:
    """Resource dictionary with parent lookup.

    Example:
        >>> parent = XpsResourceDictionary(items={"a": 1})
        >>> child = XpsResourceDictionary(items={"b": 2}, parent=parent)
        >>> child.resolve("a")
        1
    """
    items: dict[str, object]
    parent: "XpsResourceDictionary | None" = None

    def resolve(self, key: str) -> object | None:
        if key in self.items:
            return self.items[key]
        if self.parent is not None:
            return self.parent.resolve(key)
        return None
