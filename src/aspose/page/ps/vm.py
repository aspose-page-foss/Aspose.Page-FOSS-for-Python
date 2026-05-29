"""PostScript VM save/restore semantics."""

from __future__ import annotations

from dataclasses import dataclass

from .context import GraphicsState, ExecutionContext
from .objects import PsDict, PsObject
from .stack import PsStack


@dataclass
class PsSaveState:
    # PostScript `save`/`restore` does not roll back the operand or execution
    # stacks. We keep placeholders for backward compatibility with existing
    # save-state objects, but they are intentionally not used by restore.
    operand_stack: PsStack[PsObject]
    execution_stack: PsStack[PsObject]
    dictionary_stack: PsStack[PsDict]
    graphics_state_stack: PsStack[GraphicsState]


def save_state(ctx: ExecutionContext) -> PsSaveState:
    graphics_state_stack = PsStack([state.clone() for state in ctx.graphics_state_stack.to_list()])
    return PsSaveState(
        operand_stack=PsStack(),
        execution_stack=PsStack(),
        dictionary_stack=ctx.dictionary_stack.clone(),
        graphics_state_stack=graphics_state_stack,
    )


def restore_state(ctx: ExecutionContext, state: PsSaveState) -> None:
    # Keep current operand/execution stacks per PostScript semantics.
    ctx.dictionary_stack = state.dictionary_stack.clone()
    ctx.graphics_state_stack = state.graphics_state_stack.clone()
