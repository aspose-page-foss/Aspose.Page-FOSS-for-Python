"""Tokenizer for PostScript/EPS input."""

from __future__ import annotations

import base64
from dataclasses import dataclass

_DELIMITERS = set("[]{}()<>/")
_WHITESPACE = set(" \t\r\n\f\0")
_HEX_DIGITS = set("0123456789abcdefABCDEF")


@dataclass
class PsToken:
    """Represents a token from a PostScript/EPS input stream.

    Example:
        >>> token = PsToken("number", 3.14)
        >>> token.kind
        'number'
    """

    kind: str
    value: object


class PsTokenizer:
    """Tokenize PostScript/EPS bytes into language tokens.

    Example:
        >>> tokenizer = PsTokenizer(b"/Helvetica 12 selectfont")
        >>> tokenizer.next_token().kind
        'name'
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self._length = len(data)
        self._literal_array_depth = 0

    def next_token(self) -> PsToken | None:
        """Return the next token or None when input is exhausted.

        Example:
            >>> tokenizer = PsTokenizer(b"(hi) 2")
            >>> tokenizer.next_token().kind
            'string'
        """
        self._skip_whitespace()
        if self._pos >= self._length:
            return None
        ch = chr(self._data[self._pos])

        if ch == "%":
            return self._read_comment()
        if ch == "[":
            self._pos += 1
            if self._looks_like_literal_array():
                self._literal_array_depth += 1
                return PsToken("array_start", "[")
            return PsToken("name", ("[", False))
        if ch == "]":
            self._pos += 1
            if self._literal_array_depth > 0:
                self._literal_array_depth -= 1
                return PsToken("array_end", "]")
            return PsToken("name", ("]", False))
        if ch == "{":
            self._pos += 1
            return PsToken("procedure_start", "{")
        if ch == "}":
            self._pos += 1
            return PsToken("procedure_end", "}")
        if ch == "<":
            if self._peek(1) == "<":
                self._pos += 2
                return PsToken("dict_start", "<<")
            return self._read_hex_string()
        if ch == ">":
            if self._peek(1) == ">":
                self._pos += 2
                return PsToken("dict_end", ">>")
            # Be permissive with malformed streams where a dangling '>' may
            # remain after tolerant hex-string parsing.
            self._pos += 1
            return self.next_token()
        if ch == "(":
            return self._read_string()

        if ch in "+-" or ch.isdigit() or ch == ".":
            token = self._read_number_or_name()
            if token is not None:
                return token

        return self._read_name()

    def _skip_whitespace(self) -> None:
        while self._pos < self._length:
            ch = chr(self._data[self._pos])
            if ch in _WHITESPACE:
                self._pos += 1
                continue
            if ch == "%":
                break
            return

    def _peek(self, offset: int) -> str:
        pos = self._pos + offset
        if pos >= self._length:
            return ""
        return chr(self._data[pos])

    def _looks_like_literal_array(self) -> bool:
        """Heuristic for distinguishing array literals from mark-operator usage."""
        index = self._pos
        bracket_depth = 1
        procedure_depth = 0
        while index < self._length:
            ch = chr(self._data[index])
            if ch in _WHITESPACE:
                index += 1
                continue
            if ch == "%":
                while index < self._length and chr(self._data[index]) not in "\r\n":
                    index += 1
                continue
            if ch == "(":
                index = self._skip_string(index + 1)
                continue
            if ch == "[":
                bracket_depth += 1
                index += 1
                continue
            if ch == "]":
                bracket_depth -= 1
                index += 1
                if bracket_depth == 0:
                    return True
                continue
            if ch == "{":
                procedure_depth += 1
                index += 1
                continue
            if ch == "}":
                if procedure_depth == 0:
                    return False
                procedure_depth -= 1
                index += 1
                continue
            index += 1
        return False

    def _skip_string(self, index: int) -> int:
        depth = 1
        while index < self._length and depth > 0:
            ch = chr(self._data[index])
            if ch == "\\":
                index += 2
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            index += 1
        return index

    def _read_comment(self) -> PsToken:
        start = self._pos + 1
        while self._pos < self._length:
            ch = chr(self._data[self._pos])
            if ch in "\r\n":
                break
            self._pos += 1
        value = self._data[start:self._pos].decode("latin-1", errors="ignore")
        return PsToken("comment", value)

    def _read_string(self) -> PsToken:
        self._pos += 1
        depth = 1
        buf: list[int] = []
        while self._pos < self._length and depth > 0:
            ch = chr(self._data[self._pos])
            if ch == "\\":
                self._pos += 1
                if self._pos >= self._length:
                    break
                esc = chr(self._data[self._pos])
                mapped = {
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                    "b": "\b",
                    "f": "\f",
                    "\\": "\\",
                    "(": "(",
                    ")": ")",
                }.get(esc)
                if mapped is not None:
                    buf.extend(mapped.encode("latin-1"))
                elif esc.isdigit():
                    octal = esc
                    for _ in range(2):
                        if self._pos + 1 < self._length and chr(self._data[self._pos + 1]).isdigit():
                            self._pos += 1
                            octal += chr(self._data[self._pos])
                        else:
                            break
                    buf.append(int(octal, 8) & 0xFF)
                else:
                    buf.append(ord(esc))
                self._pos += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    self._pos += 1
                    break
            if depth > 0:
                buf.append(self._data[self._pos])
                self._pos += 1
        return PsToken("string", bytes(buf))

    def _read_hex_string(self) -> PsToken:
        self._pos += 1
        # ASCII85 literal string form: <~ ... ~>
        if self._pos < self._length and chr(self._data[self._pos]) == "~":
            self._pos += 1
            start = self._pos
            while self._pos < self._length:
                if (
                    chr(self._data[self._pos]) == "~"
                    and self._pos + 1 < self._length
                    and chr(self._data[self._pos + 1]) == ">"
                ):
                    payload = self._data[start:self._pos]
                    self._pos += 2
                    try:
                        raw = base64.a85decode(payload, adobe=False)
                    except Exception:
                        raw = payload
                    return PsToken("string", raw)
                self._pos += 1
            return PsToken("string", self._data[start:self._pos])

        hex_chars: list[str] = []
        while self._pos < self._length:
            ch = chr(self._data[self._pos])
            if ch == ">":
                self._pos += 1
                break
            if ch in _WHITESPACE:
                self._pos += 1
                continue
            if ch not in _HEX_DIGITS:
                # Be permissive with malformed input streams in the wild:
                # consume until the terminating '>' so parsing can continue.
                while self._pos < self._length and chr(self._data[self._pos]) != ">":
                    self._pos += 1
                if self._pos < self._length and chr(self._data[self._pos]) == ">":
                    self._pos += 1
                break
            hex_chars.append(ch)
            self._pos += 1
        if len(hex_chars) % 2 == 1:
            hex_chars.append("0")
        raw = bytes.fromhex("".join(hex_chars)) if hex_chars else b""
        return PsToken("string", raw)

    def _read_number_or_name(self) -> PsToken | None:
        start = self._pos
        token = self._read_until_delimiter()
        if token == "+" or token == "-" or token == ".":
            self._pos = start
            return None
        try:
            radix_value = _parse_radix_integer(token)
            if radix_value is not None:
                return PsToken("number", radix_value)
            if any(ch in token for ch in (".", "e", "E")):
                return PsToken("number", float(token))
            return PsToken("number", int(token))
        except ValueError:
            self._pos = start
            return None

    def _read_name(self) -> PsToken:
        literal = False
        if self._data[self._pos:self._pos + 1] == b"/":
            literal = True
            self._pos += 1
        name = self._read_until_delimiter()
        return PsToken("name", (name, literal))

    def _read_until_delimiter(self) -> str:
        start = self._pos
        while self._pos < self._length:
            ch = chr(self._data[self._pos])
            if ch in _WHITESPACE or ch in _DELIMITERS or ch == "%":
                break
            self._pos += 1
        return self._data[start:self._pos].decode("latin-1", errors="ignore")

    # Stream helpers used by runtime operators (eg image data sources).
    def read_asciihex_decoded(self, max_bytes: int) -> tuple[bytes, bool]:
        if max_bytes <= 0:
            return b"", True
        nibbles: list[str] = []
        ended = False
        while self._pos < self._length and len(nibbles) < max_bytes * 2:
            ch = chr(self._data[self._pos])
            if ch in _WHITESPACE:
                self._pos += 1
                continue
            if ch == ">":
                self._pos += 1
                ended = True
                break
            if ch not in _HEX_DIGITS:
                ended = True
                break
            nibbles.append(ch)
            self._pos += 1
        if len(nibbles) % 2 == 1:
            nibbles.append("0")
        decoded = bytes.fromhex("".join(nibbles)) if nibbles else b""
        complete = len(decoded) >= max_bytes
        if len(decoded) > max_bytes:
            decoded = decoded[:max_bytes]
        return decoded, complete and not ended

    def read_asciihex_source(self, max_decoded_bytes: int) -> bytes:
        if max_decoded_bytes <= 0:
            return b""
        start = self._pos
        nibbles = 0
        while self._pos < self._length and nibbles < max_decoded_bytes * 2:
            ch = chr(self._data[self._pos])
            if ch in _WHITESPACE:
                self._pos += 1
                continue
            if ch == ">":
                self._pos += 1
                break
            if ch not in _HEX_DIGITS:
                break
            nibbles += 1
            self._pos += 1
        return self._data[start:self._pos]

    def read_until_asciihex_eod(self) -> bytes:
        start = self._pos
        while self._pos < self._length:
            if self._data[self._pos] == ord(">"):
                self._pos += 1
                break
            self._pos += 1
        return self._data[start:self._pos]

    def read_until_ascii85_eod(self) -> bytes:
        start = self._pos
        while self._pos < self._length:
            if (
                self._data[self._pos] == ord("~")
                and self._pos + 1 < self._length
                and self._data[self._pos + 1] == ord(">")
            ):
                self._pos += 2
                break
            self._pos += 1
        return self._data[start:self._pos]

    def read_raw(self, count: int) -> bytes:
        if count <= 0:
            return b""
        end = min(self._length, self._pos + count)
        data = self._data[self._pos:end]
        self._pos = end
        return data

    def read_remaining(self) -> bytes:
        data = self._data[self._pos :]
        self._pos = self._length
        return data


def _parse_radix_integer(token: str) -> int | None:
    sign = 1
    body = token
    if body.startswith("+"):
        body = body[1:]
    elif body.startswith("-"):
        sign = -1
        body = body[1:]
    if "#" not in body:
        return None
    base_text, number_text = body.split("#", 1)
    if not base_text or not number_text:
        raise ValueError("invalid radix number")
    base = int(base_text)
    if base < 2 or base > 36:
        raise ValueError("invalid radix")
    return sign * int(number_text, base)
