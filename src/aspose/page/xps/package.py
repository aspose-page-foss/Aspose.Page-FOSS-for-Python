"""XPS package loading utilities."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from zipfile import ZipFile
import re


@dataclass
class XpsPackage:
    """Represents an XPS package.

    Example:
        >>> from io import BytesIO
        >>> from zipfile import ZipFile
        >>> buffer = BytesIO()
        >>> with ZipFile(buffer, "w") as zf:
        ...     _ = zf.writestr("FixedDocSeq.fdseq", "<FixedDocumentSequence/>")
        >>> pkg = XpsPackage.from_bytes(buffer.getvalue())
        >>> pkg.has_part("/FixedDocSeq.fdseq")
        True
    """

    parts: dict[str, bytes]

    @classmethod
    def from_bytes(cls, data: bytes) -> "XpsPackage":
        """Create an XPS package from bytes."""
        parts: dict[str, bytes] = {}
        piece_parts: dict[str, dict[int, bytes]] = {}
        piece_last_index: dict[str, int] = {}
        with ZipFile(BytesIO(data)) as archive:
            for name in archive.namelist():
                piece = _parse_piece_name(name)
                if piece is not None:
                    base, index, is_last = piece
                    bucket = piece_parts.setdefault(base, {})
                    bucket[index] = archive.read(name)
                    if is_last:
                        piece_last_index[base] = index
                    continue
                normalized = _normalize_part(name)
                parts[normalized] = archive.read(name)
        for base, chunks in piece_parts.items():
            if not chunks:
                continue
            max_index = piece_last_index.get(base)
            if max_index is None:
                max_index = max(chunks)
            data_parts: list[bytes] = []
            for index in range(max_index + 1):
                if index in chunks:
                    data_parts.append(chunks[index])
            parts[_normalize_part(base)] = b"".join(data_parts)
        return cls(parts=parts)

    @classmethod
    def from_file(cls, path: str) -> "XpsPackage":
        """Create an XPS package from a file path."""
        with open(path, "rb") as handle:
            data = handle.read()
        return cls.from_bytes(data)

    def read(self, part_name: str) -> bytes:
        """Read a package part by name."""
        key = _normalize_part(part_name)
        if key not in self.parts:
            raise ValueError(f"missing part {key}")
        return self.parts[key]

    def has_part(self, part_name: str) -> bool:
        """Check whether a package part exists."""
        return _normalize_part(part_name) in self.parts


def _normalize_part(name: str) -> str:
    if not name.startswith("/"):
        return "/" + name
    return name


def _parse_piece_name(name: str) -> tuple[str, int, bool] | None:
    match = re.match(r"^(?P<base>.+)/\[(?P<idx>\d+)\](?P<last>\.last)?\.piece$", name)
    if not match:
        return None
    base = match.group("base")
    idx = int(match.group("idx"))
    is_last = match.group("last") is not None
    return base, idx, is_last
