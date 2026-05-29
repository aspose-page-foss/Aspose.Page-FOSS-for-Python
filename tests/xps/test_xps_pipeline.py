import sys
from io import BytesIO
from pathlib import Path
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import RenderModelBuilder, PathCommand
from aspose.page.xps.images import decode_png
from aspose.page.xps.package import XpsPackage
from aspose.page.xps.parser import XpsParser
from aspose.page.xps.render import XpsRenderer
from aspose.page.xps.images import XpsImageStore


def _build_xps_package() -> bytes:
    fdseq = """<FixedDocumentSequence xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<DocumentReference Source=\"Documents/1/FixedDoc.fdoc\" />
</FixedDocumentSequence>"""
    fdoc = """<FixedDocument xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<PageContent Source=\"Pages/1.fpage\" />
</FixedDocument>"""
    fpage = """<FixedPage xmlns=\"http://schemas.microsoft.com/xps/2005/06\" Width=\"10\" Height=\"10\">
<Path Data=\"M 0,0 L 10,0 L 10,10 L 0,10 Z\" Fill=\"#FF0000\" />
</FixedPage>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocSeq.fdseq", fdseq)
        zip_file.writestr("Documents/1/FixedDoc.fdoc", fdoc)
        zip_file.writestr("Documents/1/Pages/1.fpage", fpage)
    return buffer.getvalue()


def _build_pieced_package() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocumentSequence.fdseq/[0].piece", b"ABC")
        zip_file.writestr("FixedDocumentSequence.fdseq/[1].last.piece", b"DEF")
    return buffer.getvalue()


def _build_xps_package_with_resource() -> bytes:
    fdseq = """<FixedDocumentSequence xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<DocumentReference Source=\"Documents/1/FixedDoc.fdoc\" />
</FixedDocumentSequence>"""
    fdoc = """<FixedDocument xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<PageContent Source=\"Pages/1.fpage\" />
</FixedDocument>"""
    fpage = (
        """<FixedPage xmlns=\"http://schemas.microsoft.com/xps/2005/06\" xmlns:x=\"http://schemas.microsoft.com/xps/2005/06\">
<FixedPage.Resources>
  <ResourceDictionary>
    <PathGeometry x:Key=\"R1\" Figures=\"M 0,0 L 1,0 L 1,1 Z\" />
  </ResourceDictionary>
</FixedPage.Resources>
<Path Data=\"{StaticResource R1}\" Fill=\"#000000\" />
</FixedPage>"""
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocSeq.fdseq", fdseq)
        zip_file.writestr("Documents/1/FixedDoc.fdoc", fdoc)
        zip_file.writestr("Documents/1/Pages/1.fpage", fpage)
    return buffer.getvalue()


def _minimal_png() -> bytes:
    import zlib
    import struct

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_chunk = _png_chunk(b"IHDR", ihdr)
    raw = b"\x00\xFF\x00\x00"
    idat_chunk = _png_chunk(b"IDAT", zlib.compress(raw))
    iend_chunk = _png_chunk(b"IEND", b"")
    return signature + ihdr_chunk + idat_chunk + iend_chunk


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    import zlib
    import struct

    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return length + tag + data + crc


class TestXpsPipeline(unittest.TestCase):
    def test_package_and_parser(self) -> None:
        data = _build_xps_package()
        package = XpsPackage.from_bytes(data)
        parser = XpsParser(package)
        parts = parser.fixed_page_parts()
        self.assertEqual(parts, ["/Documents/1/Pages/1.fpage"])

    def test_package_pieces(self) -> None:
        data = _build_pieced_package()
        package = XpsPackage.from_bytes(data)
        self.assertEqual(package.read("/FixedDocumentSequence.fdseq"), b"ABCDEF")

    def test_path_static_resource(self) -> None:
        data = _build_xps_package_with_resource()
        package = XpsPackage.from_bytes(data)
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))
        doc = builder.document()
        self.assertEqual(len(doc.pages), 1)
        self.assertTrue(doc.pages[0].commands)

    def test_renderer_path_fill(self) -> None:
        data = _build_xps_package()
        package = XpsPackage.from_bytes(data)
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))
        doc = builder.document()
        self.assertEqual(len(doc.pages), 1)
        self.assertIsInstance(doc.pages[0].commands[0], PathCommand)

    def test_decode_png_dimensions(self) -> None:
        resource = decode_png(_minimal_png())
        self.assertEqual(resource.width, 1)
        self.assertEqual(resource.height, 1)


if __name__ == "__main__":
    unittest.main()
