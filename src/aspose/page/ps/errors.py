"""PostScript error types."""

from __future__ import annotations


class PsError(Exception):
    """Base PostScript error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class PsSyntaxError(PsError):
    def __init__(self, message: str = "syntax error") -> None:
        super().__init__("syntaxerror", message)


class PsTypeError(PsError):
    def __init__(self, message: str = "type check") -> None:
        super().__init__("typecheck", message)


class PsRangeError(PsError):
    def __init__(self, message: str = "range check") -> None:
        super().__init__("rangecheck", message)


class PsUndefinedError(PsError):
    def __init__(self, message: str = "undefined") -> None:
        super().__init__("undefined", message)


class PsIOError(PsError):
    def __init__(self, message: str = "io error") -> None:
        super().__init__("ioerror", message)


class PsLimitCheck(PsError):
    def __init__(self, message: str = "limit check") -> None:
        super().__init__("limitcheck", message)


class PsInvalidAccess(PsError):
    def __init__(self, message: str = "invalid access") -> None:
        super().__init__("invalidaccess", message)


class PsQuit(Exception):
    """Internal non-error signal used by PostScript `quit`."""
