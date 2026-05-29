"""PostScript object model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from .context import GraphicsState
    from .vm import PsSaveState
    from ..common.color_resources import Pattern


@dataclass(frozen=True)
class PsName:
    value: str
    literal: bool = False


@dataclass(frozen=True)
class PsOperator:
    name: str


@dataclass(frozen=True)
class PsString:
    value: bytes
    remaining_filter: str | None = None
    filter_params: dict | None = None


@dataclass
class PsArray:
    items: list[PsObject]


@dataclass
class PsDict:
    items: dict[object, PsObject]


@dataclass
class PsProcedure:
    items: list[PsObject]


@dataclass(frozen=True)
class PsMark:
    kind: str = "mark"


@dataclass(frozen=True)
class PsSave:
    state: PsSaveState


@dataclass(frozen=True)
class PsGState:
    state: GraphicsState


@dataclass(frozen=True)
class PsFile:
    name: str | None = None
    mode: str | None = None
    data: bytes | None = None


@dataclass(frozen=True)
class PsFontId:
    id: int | str


@dataclass(frozen=True)
class PsPattern:
    pattern_id: str
    pattern: "Pattern"


PsObject = Union[
    int,
    float,
    bool,
    None,
    PsName,
    PsOperator,
    PsString,
    PsArray,
    PsDict,
    PsProcedure,
    PsMark,
    PsSave,
    PsGState,
    PsFile,
    PsFontId,
    PsPattern,
]
