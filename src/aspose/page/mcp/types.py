"""MCP request/response types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class McpInput:
    """MCP input payload.

    Example:
        >>> McpInput(input_path="sample.ps", input_bytes_b64=None)
        McpInput(input_path='sample.ps', input_bytes_b64=None)
    """

    input_path: str | None
    input_bytes_b64: str | None


@dataclass
class McpOutput:
    """MCP output configuration.

    Example:
        >>> McpOutput(output_path=None, return_bytes=True)
        McpOutput(output_path=None, return_bytes=True)
    """

    output_path: str | None
    return_bytes: bool


@dataclass
class McpConversionOptions:
    """Conversion options for MCP operations.

    Example:
        >>> McpConversionOptions(format="png", dpi=300)
        McpConversionOptions(format='png', dpi=300, no_compress=False)
    """

    format: str | None
    dpi: int | None
    no_compress: bool = False


@dataclass
class McpResult:
    """MCP output payload.

    Example:
        >>> McpResult(output_path="out.pdf", output_bytes_b64=None)
        McpResult(output_path='out.pdf', output_bytes_b64=None)
    """

    output_path: str | None
    output_bytes_b64: str | None
