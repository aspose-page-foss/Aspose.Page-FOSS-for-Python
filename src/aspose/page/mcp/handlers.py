"""MCP conversion handlers (dependency-free)."""

from __future__ import annotations

import base64
from dataclasses import asdict

from ..ps.dsc import parse_dsc_comments
from ..ps.document import PsDocument
from ..ps.output import ImageSaveOptions, PdfSaveOptions
from ..xps.document import XpsDocument
from .types import McpConversionOptions, McpInput, McpOutput, McpResult


def ps_to_pdf(
    input: McpInput,
    output: McpOutput,
    options: McpConversionOptions | None = None,
) -> McpResult:
    """Convert PS/EPS to PDF bytes or file output.

    Example:
        >>> payload = McpInput(input_path="sample.ps", input_bytes_b64=None)
        >>> ps_to_pdf(payload, McpOutput(output_path=None, return_bytes=True)).output_bytes_b64 is not None
        True
    """
    source_bytes, source_path = _resolve_input(input)
    try:
        document = PsDocument.from_file(source_path) if source_path else PsDocument.from_bytes(source_bytes)
        pdf_options = PdfSaveOptions(no_compression=bool(options.no_compress)) if options else PdfSaveOptions()
        data = document.to_pdf(pdf_options)
        return _finalize_output(data, output)
    except Exception as exc:
        raise RuntimeError(f"PS to PDF failed: {exc}") from exc


def ps_to_image(input: McpInput, output: McpOutput, options: McpConversionOptions) -> McpResult:
    """Convert PS/EPS to raster image bytes or file output.

    Example:
        >>> payload = McpInput(input_path="sample.ps", input_bytes_b64=None)
        >>> opts = McpConversionOptions(format="png", dpi=72)
        >>> ps_to_image(payload, McpOutput(output_path=None, return_bytes=True), opts).output_bytes_b64 is not None
        True
    """
    source_bytes, source_path = _resolve_input(input)
    if options is None or not options.format:
        raise ValueError("image format is required")
    dpi = options.dpi if options.dpi is not None else 300
    try:
        document = PsDocument.from_file(source_path) if source_path else PsDocument.from_bytes(source_bytes)
        image_options = ImageSaveOptions(format=options.format, dpi=dpi)
        data = document.to_image(image_options)
        return _finalize_output(data, output)
    except Exception as exc:
        raise RuntimeError(f"PS to image failed: {exc}") from exc


def xps_to_pdf(
    input: McpInput,
    output: McpOutput,
    options: McpConversionOptions | None = None,
) -> McpResult:
    """Convert XPS to PDF bytes or file output.

    Example:
        >>> payload = McpInput(input_path="sample.xps", input_bytes_b64=None)
        >>> xps_to_pdf(payload, McpOutput(output_path=None, return_bytes=True)).output_bytes_b64 is not None
        True
    """
    source_bytes, source_path = _resolve_input(input)
    try:
        document = XpsDocument.from_file(source_path) if source_path else XpsDocument.from_bytes(source_bytes)
        pdf_options = PdfSaveOptions(no_compression=bool(options.no_compress)) if options else PdfSaveOptions()
        data = document.to_pdf(pdf_options)
        return _finalize_output(data, output)
    except Exception as exc:
        raise RuntimeError(f"XPS to PDF failed: {exc}") from exc


def xps_to_image(input: McpInput, output: McpOutput, options: McpConversionOptions) -> McpResult:
    """Convert XPS to raster image bytes or file output.

    Example:
        >>> payload = McpInput(input_path="sample.xps", input_bytes_b64=None)
        >>> opts = McpConversionOptions(format="png", dpi=72)
        >>> xps_to_image(payload, McpOutput(output_path=None, return_bytes=True), opts).output_bytes_b64 is not None
        True
    """
    source_bytes, source_path = _resolve_input(input)
    if options is None or not options.format:
        raise ValueError("image format is required")
    dpi = options.dpi if options.dpi is not None else 300
    try:
        document = XpsDocument.from_file(source_path) if source_path else XpsDocument.from_bytes(source_bytes)
        image_options = ImageSaveOptions(format=options.format, dpi=dpi)
        data = document.to_image(image_options)
        return _finalize_output(data, output)
    except Exception as exc:
        raise RuntimeError(f"XPS to image failed: {exc}") from exc


def eps_metadata(input: McpInput) -> dict[str, object]:
    """Extract EPS DSC metadata as a JSON-serializable dict.

    Example:
        >>> payload = McpInput(input_path="sample.eps", input_bytes_b64=None)
        >>> isinstance(eps_metadata(payload), dict)
        True
    """
    source_bytes, source_path = _resolve_input(input)
    data = source_bytes
    if source_path:
        with open(source_path, "rb") as handle:
            data = handle.read()
    meta = parse_dsc_comments(data)
    return asdict(meta)


def _resolve_input(input: McpInput) -> tuple[bytes, str | None]:
    if bool(input.input_path) == bool(input.input_bytes_b64):
        raise ValueError("provide exactly one of input_path or input_bytes_b64")
    if input.input_path:
        with open(input.input_path, "rb") as handle:
            return handle.read(), input.input_path
    payload = base64.b64decode(input.input_bytes_b64 or "")
    return payload, None


def _finalize_output(data: bytes, output: McpOutput) -> McpResult:
    output_path = None
    output_b64 = None
    if output.output_path:
        with open(output.output_path, "wb") as handle:
            handle.write(data)
        output_path = output.output_path
    if output.return_bytes:
        output_b64 = base64.b64encode(data).decode("ascii")
    return McpResult(output_path=output_path, output_bytes_b64=output_b64)
