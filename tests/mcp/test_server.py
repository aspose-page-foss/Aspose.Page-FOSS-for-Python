import sys
from pathlib import Path
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.mcp import server as mcp_server


class _FakeFastMCP:
    def __init__(self, name: str) -> None:
        self.name = name
        self.tools = []
        self.run_calls = []

    def tool(self, func) -> None:
        self.tools.append(func)

    def run(self, host: str, port: int) -> None:
        self.run_calls.append((host, port))


class TestMcpServer(unittest.TestCase):
    def test_create_server_registers_all_tools(self) -> None:
        fake_module = types.ModuleType("fastmcp")
        fake_module.FastMCP = _FakeFastMCP

        with patch.dict(sys.modules, {"fastmcp": fake_module}):
            server = mcp_server.create_server()

        self.assertEqual(server.name, "Aspose.Page")
        self.assertEqual(
            [tool.__name__ for tool in server.tools],
            ["ps_to_pdf", "ps_to_image", "xps_to_pdf", "xps_to_image", "eps_metadata"],
        )

    def test_run_invokes_server_with_host_port(self) -> None:
        fake = _FakeFastMCP("Aspose.Page")
        with patch("aspose.page.mcp.server.create_server", return_value=fake):
            mcp_server.run(host="0.0.0.0", port=8123)
        self.assertEqual(fake.run_calls, [("0.0.0.0", 8123)])


if __name__ == "__main__":
    unittest.main()
