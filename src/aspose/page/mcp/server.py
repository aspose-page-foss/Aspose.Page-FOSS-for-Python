"""FastMCP server bindings for Aspose.Page conversions."""

from __future__ import annotations

from .handlers import eps_metadata, ps_to_image, ps_to_pdf, xps_to_image, xps_to_pdf


def create_server() -> object:
    """Create a FastMCP server and register conversion tools.

    Example:
        >>> isinstance(create_server(), object)
        True
    """
    try:
        from fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError("FastMCP is required to run the MCP server") from exc

    server = FastMCP("Aspose.Page")
    server.tool(ps_to_pdf)
    server.tool(ps_to_image)
    server.tool(xps_to_pdf)
    server.tool(xps_to_image)
    server.tool(eps_metadata)
    return server


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the MCP server.

    Example:
        >>> isinstance(run, object)
        True
    """
    server = create_server()
    server.run(host=host, port=port)
