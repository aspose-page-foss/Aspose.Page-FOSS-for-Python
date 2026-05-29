import base64
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.mcp.handlers import eps_metadata, ps_to_image, ps_to_pdf, xps_to_pdf
from aspose.page.mcp.types import McpConversionOptions, McpInput, McpOutput


class TestMcpHandlers(unittest.TestCase):
    def test_ps_to_pdf_from_bytes(self) -> None:
        ps_bytes = b"%!PS-Adobe-3.0\n0 0 moveto 10 0 lineto stroke\n"
        input_payload = McpInput(input_path=None, input_bytes_b64=base64.b64encode(ps_bytes).decode("ascii"))
        output = McpOutput(output_path=None, return_bytes=True)
        result = ps_to_pdf(input_payload, output)
        self.assertIsNotNone(result.output_bytes_b64)
        self.assertTrue(base64.b64decode(result.output_bytes_b64).startswith(b"%PDF"))

    def test_ps_to_image_requires_format(self) -> None:
        ps_bytes = b"%!PS-Adobe-3.0\n0 0 moveto 10 0 lineto stroke\n"
        input_payload = McpInput(input_path=None, input_bytes_b64=base64.b64encode(ps_bytes).decode("ascii"))
        output = McpOutput(output_path=None, return_bytes=True)
        with self.assertRaises(ValueError):
            ps_to_image(input_payload, output, McpConversionOptions(format=None, dpi=72))

    def test_eps_metadata_extracts_fields(self) -> None:
        eps_bytes = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 20\n%%Title: Sample\n"
        input_payload = McpInput(input_path=None, input_bytes_b64=base64.b64encode(eps_bytes).decode("ascii"))
        meta = eps_metadata(input_payload)
        self.assertEqual(meta.get("bounding_box"), (0, 0, 10, 20))
        self.assertEqual(meta.get("title"), "Sample")

    def test_xps_to_pdf_from_file(self) -> None:
        path = Path("testdata/xps/integration/Simple.xps")
        input_payload = McpInput(input_path=str(path), input_bytes_b64=None)
        output = McpOutput(output_path=None, return_bytes=True)
        result = xps_to_pdf(input_payload, output)
        self.assertTrue(base64.b64decode(result.output_bytes_b64).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
