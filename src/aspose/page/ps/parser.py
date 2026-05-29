"""Parser for PostScript/EPS tokens."""

from __future__ import annotations

from .errors import PsSyntaxError
from .objects import PsName, PsProcedure, PsString, PsObject
from .tokenizer import PsTokenizer, PsToken


class PsParser:
    """Parse PostScript/EPS tokens into language objects.

    Example:
        >>> tokenizer = PsTokenizer(b"/name 1")
        >>> parser = PsParser(tokenizer)
        >>> parser.parse_object().value
        'name'
    """

    def __init__(self, tokenizer: PsTokenizer) -> None:
        self._tokenizer = tokenizer
        self._buffer: list[PsToken] = []

    def parse_object(self) -> PsObject | None:
        """Parse a single PostScript object or return None at EOF.

        Example:
            >>> parser = PsParser(PsTokenizer(b"42"))
            >>> parser.parse_object()
            42
        """
        token = self._next_non_comment()
        if token is None:
            return None
        if token.kind == "number":
            return token.value
        if token.kind == "name":
            name, literal = token.value
            return PsName(name, literal=literal)
        if token.kind == "string":
            return PsString(token.value)
        if token.kind == "array_start":
            return PsName("[", literal=False)
        if token.kind == "dict_start":
            return PsName("<<", literal=False)
        if token.kind == "procedure_start":
            return self._parse_procedure()
        if token.kind == "dict_end":
            return PsName(">>", literal=False)
        if token.kind == "array_end":
            return PsName("]", literal=False)
        if token.kind in ("procedure_end",):
            raise PsSyntaxError(f"unexpected token {token.kind}")
        return None

    def parse_all(self) -> list[PsObject]:
        """Parse all remaining objects from the token stream.

        Example:
            >>> parser = PsParser(PsTokenizer(b"1 2 3"))
            >>> parser.parse_all()
            [1, 2, 3]
        """
        objects: list[PsObject] = []
        while True:
            obj = self.parse_object()
            if obj is None:
                break
            objects.append(obj)
        return objects

    def _parse_procedure(self) -> PsProcedure:
        items: list[PsObject] = []
        while True:
            token = self._next_non_comment()
            if token is None:
                raise PsSyntaxError("unterminated procedure")
            if token.kind == "procedure_end":
                break
            self._push_token(token)
            item = self.parse_object()
            if item is None:
                raise PsSyntaxError("unterminated procedure")
            items.append(item)
        return PsProcedure(items)

    def _next_non_comment(self) -> PsToken | None:
        while True:
            token = self._next_token()
            if token is None:
                return None
            if token.kind != "comment":
                return token

    def _next_token(self) -> PsToken | None:
        if self._buffer:
            return self._buffer.pop()
        return self._tokenizer.next_token()

    def _push_token(self, token: PsToken) -> None:
        self._buffer.append(token)
