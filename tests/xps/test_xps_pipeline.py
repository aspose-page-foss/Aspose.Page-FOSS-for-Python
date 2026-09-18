import sys
from io import BytesIO
from pathlib import Path
import re
import unittest
from zipfile import ZipFile
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import (
    ClipCommand,
    ImageCommand,
    Matrix,
    PathCommand,
    RenderModelBuilder,
    StateRestoreCommand,
    StateSaveCommand,
    TextCommand,
)
from aspose.page.xps.document import XpsDocument
from aspose.page.xps.images import decode_jpeg, decode_png
from aspose.page.xps.output import _build_xps_render_document, _job_media_size_points
from aspose.page.xps.package import XpsPackage
from aspose.page.xps.parser import XpsParser
from aspose.page.xps.render import (
    XpsRenderer,
    _image_brush_to_pattern,
    _gradient_to_pattern,
    _parse_path_data,
    _parse_path_geometry_element,
    _sample_brush_coordinates,
)
from aspose.page.xps.images import XpsImageStore
from aspose.page.image.skia_raster_writer import _apply_soft_mask_to_rgba
from aspose.page.ps.output import ImageSaveOptions


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


def _palette_png_4bit() -> bytes:
    def chunk(chunk_type: bytes, payload: bytes) -> bytes:
        import struct
        import zlib

        return (
            struct.pack(">I", len(payload))
            + chunk_type
            + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
        )

    import struct
    import zlib

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 4, 3, 0, 0, 0))
    plte = chunk(b"PLTE", bytes([255, 0, 0, 0, 255, 0]))
    trns = chunk(b"tRNS", bytes([255, 64]))
    # Filter byte 0, then two 4-bit palette indices: 0 and 1.
    idat = chunk(b"IDAT", zlib.compress(bytes([0x00, 0x01])))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + plte + trns + idat + iend


def _grayscale_png_1bit() -> bytes:
    def chunk(chunk_type: bytes, payload: bytes) -> bytes:
        import struct
        import zlib

        return (
            struct.pack(">I", len(payload))
            + chunk_type
            + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
        )

    import struct
    import zlib

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 1, 0, 0, 0, 0))
    # Filter byte 0, then packed 1-bit pixels: 0 (black), 1 (white).
    idat = chunk(b"IDAT", zlib.compress(bytes([0x00, 0x40])))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _grayscale_jpeg() -> bytes:
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on environment
        raise unittest.SkipTest("Pillow not installed") from exc
    image = Image.new("L", (3, 2), color=180)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", dpi=(96, 96))
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


def _build_xps_package_with_external_resource_dictionary() -> bytes:
    fdseq = """<FixedDocumentSequence xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<DocumentReference Source=\"Documents/1/FixedDoc.fdoc\" />
</FixedDocumentSequence>"""
    fdoc = """<FixedDocument xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<PageContent Source=\"Pages/1.fpage\" />
</FixedDocument>"""
    fpage = """<FixedPage xmlns=\"http://schemas.microsoft.com/xps/2005/06\" xmlns:x=\"http://schemas.microsoft.com/xps/2005/06/resourcedictionary-key\" Width=\"10\" Height=\"10\">
<FixedPage.Resources>
  <ResourceDictionary Source=\"/Resources/resources.dict\" />
</FixedPage.Resources>
<Path Stroke=\"{StaticResource magenta}\" StrokeThickness=\"2\" Data=\"M 1,1 L 9,1\" />
</FixedPage>"""
    resources = """<ResourceDictionary xmlns=\"http://schemas.microsoft.com/xps/2005/06\" xmlns:x=\"http://schemas.microsoft.com/xps/2005/06/resourcedictionary-key\">
  <SolidColorBrush x:Key=\"magenta\" Color=\"#FF00FF\" />
</ResourceDictionary>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocSeq.fdseq", fdseq)
        zip_file.writestr("Documents/1/FixedDoc.fdoc", fdoc)
        zip_file.writestr("Documents/1/Pages/1.fpage", fpage)
        zip_file.writestr("Resources/resources.dict", resources)
    return buffer.getvalue()


def _build_xps_package_with_transform_resource() -> bytes:
    fdseq = """<FixedDocumentSequence xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<DocumentReference Source=\"Documents/1/FixedDoc.fdoc\" />
</FixedDocumentSequence>"""
    fdoc = """<FixedDocument xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<PageContent Source=\"Pages/1.fpage\" />
</FixedDocument>"""
    fpage = """<FixedPage xmlns=\"http://schemas.microsoft.com/xps/2005/06\" xmlns:x=\"http://schemas.microsoft.com/xps/2005/06/resourcedictionary-key\" Width=\"10\" Height=\"10\">
<FixedPage.Resources>
  <ResourceDictionary>
    <MatrixTransform x:Key=\"rotate\" Matrix=\"0,1,-1,0,10,0\" />
  </ResourceDictionary>
</FixedPage.Resources>
<Path RenderTransform=\"{StaticResource rotate}\" Data=\"M 0,0 L 2,0\" Stroke=\"#000000\" StrokeThickness=\"1\" />
</FixedPage>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocSeq.fdseq", fdseq)
        zip_file.writestr("Documents/1/FixedDoc.fdoc", fdoc)
        zip_file.writestr("Documents/1/Pages/1.fpage", fpage)
    return buffer.getvalue()


def _build_xps_package_with_child_render_transform() -> bytes:
    fdseq = """<FixedDocumentSequence xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<DocumentReference Source=\"Documents/1/FixedDoc.fdoc\" />
</FixedDocumentSequence>"""
    fdoc = """<FixedDocument xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<PageContent Source=\"Pages/1.fpage\" />
</FixedDocument>"""
    fpage = """<FixedPage xmlns=\"http://schemas.microsoft.com/xps/2005/06\" Width=\"20\" Height=\"20\">
<Canvas>
  <Canvas.RenderTransform>
    <MatrixTransform Matrix=\"2,0,0,2,0,0\" />
  </Canvas.RenderTransform>
  <Path Data=\"M 1,1 L 3,1\" Stroke=\"#000000\" StrokeThickness=\"1\" />
</Canvas>
</FixedPage>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocSeq.fdseq", fdseq)
        zip_file.writestr("Documents/1/FixedDoc.fdoc", fdoc)
        zip_file.writestr("Documents/1/Pages/1.fpage", fpage)
    return buffer.getvalue()


def _build_xps_package_with_arc_geometry() -> bytes:
    fdseq = """<FixedDocumentSequence xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<DocumentReference Source=\"Documents/1/FixedDoc.fdoc\" />
</FixedDocumentSequence>"""
    fdoc = """<FixedDocument xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<PageContent Source=\"Pages/1.fpage\" />
</FixedDocument>"""
    fpage = """<FixedPage xmlns=\"http://schemas.microsoft.com/xps/2005/06\" xmlns:x=\"http://schemas.microsoft.com/xps/2005/06/resourcedictionary-key\" Width=\"100\" Height=\"100\">
<FixedPage.Resources>
  <ResourceDictionary>
    <PathGeometry x:Key=\"oval\" Figures=\"M 20,50 A 30,20 0 0 1 80,50 30,20 0 0 1 20,50\" />
  </ResourceDictionary>
</FixedPage.Resources>
<Path Data=\"{StaticResource oval}\" Fill=\"#000000\" />
</FixedPage>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocSeq.fdseq", fdseq)
        zip_file.writestr("Documents/1/FixedDoc.fdoc", fdoc)
        zip_file.writestr("Documents/1/Pages/1.fpage", fpage)
    return buffer.getvalue()


def _build_xps_package_with_scaled_dashed_path() -> bytes:
    fdseq = """<FixedDocumentSequence xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<DocumentReference Source=\"Documents/1/FixedDoc.fdoc\" />
</FixedDocumentSequence>"""
    fdoc = """<FixedDocument xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<PageContent Source=\"Pages/1.fpage\" />
</FixedDocument>"""
    fpage = """<FixedPage xmlns=\"http://schemas.microsoft.com/xps/2005/06\" Width=\"100\" Height=\"100\">
<Canvas RenderTransform=\"0.5,0,0,0.5,0,0\">
  <Path Stroke=\"#000000\" StrokeThickness=\"2\" StrokeDashArray=\"3 1\" StrokeDashOffset=\"2\"
        StrokeDashCap=\"Flat\" StrokeLineJoin=\"Round\" Data=\"M 0,0 L 20,0\" />
</Canvas>
</FixedPage>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocSeq.fdseq", fdseq)
        zip_file.writestr("Documents/1/FixedDoc.fdoc", fdoc)
        zip_file.writestr("Documents/1/Pages/1.fpage", fpage)
    return buffer.getvalue()


def _build_xps_package_with_parent_relative_image() -> bytes:
    fdseq = """<FixedDocumentSequence xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<DocumentReference Source=\"Documents/1/FixedDoc.fdoc\" />
</FixedDocumentSequence>"""
    fdoc = """<FixedDocument xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
<PageContent Source=\"Pages/1.fpage\" />
</FixedDocument>"""
    fpage = """<FixedPage xmlns=\"http://schemas.microsoft.com/xps/2005/06\" Width=\"100\" Height=\"100\">
<Path Data=\"M 0,0 L 10,0 L 10,10 L 0,10 Z\">
  <Path.Fill>
    <ImageBrush ImageSource=\"../Resources/Images/1.JPG\" Viewbox=\"0,0,1,1\" Viewport=\"0,0,1,1\" />
  </Path.Fill>
</Path>
</FixedPage>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocSeq.fdseq", fdseq)
        zip_file.writestr("Documents/1/FixedDoc.fdoc", fdoc)
        zip_file.writestr("Documents/1/Pages/1.fpage", fpage)
        zip_file.writestr("Documents/1/Resources/Images/1.JPG", _grayscale_jpeg())
    return buffer.getvalue()


def _build_xps_package_with_landscape_job_print_ticket() -> bytes:
    fdseq = """<FixedDocumentSequence xmlns="http://schemas.microsoft.com/xps/2005/06">
<DocumentReference Source="Documents/1/FixedDoc.fdoc" />
</FixedDocumentSequence>"""
    fdoc = """<FixedDocument xmlns="http://schemas.microsoft.com/xps/2005/06">
<PageContent Source="Pages/1.fpage" />
</FixedDocument>"""
    fpage = """<FixedPage xmlns="http://schemas.microsoft.com/xps/2005/06" Width="1122.5196850393702" Height="793.70078740157476">
<Path Data="M 0,0 L 10,0 L 10,10 L 0,10 Z" Fill="#FF0000" />
</FixedPage>"""
    rels = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdPT1" Type="http://schemas.microsoft.com/xps/2005/06/printticket" Target="MetaData/Job_PT.xml" />
</Relationships>"""
    ticket = """<psf:PrintTicket xmlns:psf="http://schemas.microsoft.com/windows/2003/08/printing/printschemaframework" xmlns:psk="http://schemas.microsoft.com/windows/2003/08/printing/printschemakeywords">
<psf:Feature name="psk:PageMediaSize">
  <psf:Option name="psk:ISOA4">
    <psf:ScoredProperty name="psk:MediaSizeWidth"><psf:Value>210000</psf:Value></psf:ScoredProperty>
    <psf:ScoredProperty name="psk:MediaSizeHeight"><psf:Value>297000</psf:Value></psf:ScoredProperty>
  </psf:Option>
</psf:Feature>
<psf:Feature name="psk:PageOrientation">
  <psf:Option name="psk:Landscape" />
</psf:Feature>
</psf:PrintTicket>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("FixedDocSeq.fdseq", fdseq)
        zip_file.writestr("Documents/1/FixedDoc.fdoc", fdoc)
        zip_file.writestr("Documents/1/Pages/1.fpage", fpage)
        zip_file.writestr("_rels/FixedDocSeq.fdseq.rels", rels)
        zip_file.writestr("MetaData/Job_PT.xml", ticket)
    return buffer.getvalue()


def _build_xps_package_with_polyquadratic_geometry() -> bytes:
    return b""


def _build_minimal_image_package() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("Images/test.png", _minimal_png())
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

    def test_external_resource_dictionary_source(self) -> None:
        data = _build_xps_package_with_external_resource_dictionary()
        package = XpsPackage.from_bytes(data)
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))
        doc = builder.document()
        self.assertEqual(len(doc.pages), 1)
        self.assertTrue(doc.pages[0].commands)
        command = doc.pages[0].commands[0]
        if isinstance(command, PathCommand):
            self.assertIsNotNone(command.stroke_paint)
            self.assertEqual(command.stroke_paint.kind, "DeviceRGB")
            self.assertGreater(command.stroke_paint.value[0], 0.9)
            self.assertLess(command.stroke_paint.value[1], 0.2)
            self.assertGreater(command.stroke_paint.value[2], 0.9)
        else:
            self.assertIsInstance(command, ImageCommand)
            self.assertGreater(command.width, 0)
            self.assertGreater(command.height, 0)

    def test_static_resource_render_transform(self) -> None:
        data = _build_xps_package_with_transform_resource()
        package = XpsPackage.from_bytes(data)
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))
        command = builder.document().pages[0].commands[0]
        if isinstance(command, PathCommand):
            first_point = command.path.segments[0].points[0]
            self.assertAlmostEqual(first_point.x, 7.5, places=6)
            self.assertAlmostEqual(first_point.y, 7.5, places=6)
        else:
            self.assertIsInstance(command, ImageCommand)
            self.assertGreater(command.matrix.e, 0.0)
            self.assertGreater(command.matrix.f, 0.0)

    def test_child_render_transform_element(self) -> None:
        data = _build_xps_package_with_child_render_transform()
        package = XpsPackage.from_bytes(data)
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))
        command = builder.document().pages[0].commands[0]
        if isinstance(command, PathCommand):
            first_point = command.path.segments[0].points[0]
            self.assertAlmostEqual(first_point.x, 1.5, places=6)
            self.assertAlmostEqual(first_point.y, 13.5, places=6)
        else:
            self.assertIsInstance(command, ImageCommand)
            self.assertGreater(command.matrix.a, 0.0)

    def test_image_brush_pattern_uses_viewport_geometry(self) -> None:
        package = XpsPackage.from_bytes(_build_minimal_image_package())
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        brush = ET.fromstring(
            """<ImageBrush xmlns=\"http://schemas.microsoft.com/xps/2005/06\"
                ImageSource=\"/Images/test.png\"
                Viewbox=\"0,0,128,96\"
                Viewport=\"0,0,128,96\"
                TileMode=\"Tile\" />"""
        )

        paint = _image_brush_to_pattern(brush, builder, renderer)
        self.assertIsNotNone(paint)
        self.assertEqual(paint.kind, "Pattern")
        pattern_id = paint.value.pattern_id
        pattern = builder.document().resources.patterns[pattern_id]
        self.assertEqual(pattern.bbox, (0.0, 0.0, 128.0, 96.0))
        self.assertEqual(pattern.x_step, 128.0)
        self.assertEqual(pattern.y_step, 96.0)
        self.assertEqual(len(pattern.commands), 1)
        image_command = pattern.commands[0]
        self.assertAlmostEqual(image_command.matrix.a, 128.0, places=6)
        self.assertAlmostEqual(image_command.matrix.d, -96.0, places=6)
        self.assertAlmostEqual(image_command.matrix.f, 96.0, places=6)

    def test_image_brush_pattern_applies_paint_transform_once(self) -> None:
        package = XpsPackage.from_bytes(_build_minimal_image_package())
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        brush = ET.fromstring(
            """<ImageBrush xmlns="http://schemas.microsoft.com/xps/2005/06"
                ImageSource="/Images/test.png"
                Viewbox="0,0,258.24,56.64"
                Viewport="50,20,193.68,42.48" />"""
        )

        paint = _image_brush_to_pattern(
            brush,
            builder,
            renderer,
            paint_transform=Matrix(0.525, 0.0, 0.0, -0.525, 0.0, 792.0),
        )
        self.assertIsNotNone(paint)
        pattern = builder.document().resources.patterns[paint.value.pattern_id]
        self.assertEqual(pattern.bbox, (0.0, 0.0, 193.68, 42.48))
        self.assertAlmostEqual(pattern.matrix[0], 0.525, places=6)
        self.assertAlmostEqual(pattern.matrix[3], -0.525, places=6)
        self.assertAlmostEqual(pattern.matrix[4], 26.25, places=6)
        self.assertAlmostEqual(pattern.matrix[5], 781.5, places=6)

    def test_apply_soft_mask_to_rgba(self) -> None:
        rgba = bytearray([10, 20, 30, 255, 40, 50, 60, 255])
        result = _apply_soft_mask_to_rgba(rgba, bytes([255, 0]), 2, 1)
        self.assertEqual(list(result[:4]), [10, 20, 30, 255])
        self.assertEqual(list(result[4:8]), [0, 0, 0, 0])

    def test_parse_smooth_cubic_path_data(self) -> None:
        path = _parse_path_data(
            "M 10,150 c 25,-50 50,50 75,0 s 50,50 75,0 50,50 75,0 "
            "c -25,-50 -50,50 -75,0 s -50,50 -75,0 -50,50 -75,0",
            Matrix.identity(),
        )
        curves = [segment for segment in path.segments if segment.kind == "curve"]
        self.assertEqual(len(curves), 6)
        # The first smooth cubic must reflect the previous control point.
        first_cubic = curves[0].points
        second_cubic = curves[1].points
        self.assertAlmostEqual(second_cubic[0].x, 110.0, places=6)
        self.assertAlmostEqual(second_cubic[0].y, 100.0, places=6)
        self.assertAlmostEqual(first_cubic[2].x, 85.0, places=6)
        self.assertAlmostEqual(first_cubic[2].y, 150.0, places=6)

    def test_parse_arc_geometry_element(self) -> None:
        data = _build_xps_package_with_arc_geometry()
        package = XpsPackage.from_bytes(data)
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))
        command = builder.document().pages[0].commands[0]
        self.assertIsInstance(command, PathCommand)
        curves = [segment for segment in command.path.segments if segment.kind == "curve"]
        self.assertGreaterEqual(len(curves), 2)

    def test_parse_poly_quadratic_geometry_element(self) -> None:
        geometry = ET.fromstring(
            """<PathGeometry xmlns=\"http://schemas.microsoft.com/xps/2005/06\">
  <PathFigure StartPoint=\"10,50\" IsClosed=\"true\">
    <PolyQuadraticBezierSegment Points=\"25,10 50,50 75,90 90,50\" />
  </PathFigure>
</PathGeometry>"""
        )
        path = _parse_path_geometry_element(geometry, Matrix.identity())
        curves = [segment for segment in path.segments if segment.kind == "curve"]
        self.assertEqual(len(curves), 2)
        self.assertAlmostEqual(curves[0].points[-1].x, 50.0, places=6)
        self.assertAlmostEqual(curves[0].points[-1].y, 50.0, places=6)
        self.assertAlmostEqual(curves[1].points[-1].x, 90.0, places=6)
        self.assertAlmostEqual(curves[1].points[-1].y, 50.0, places=6)

    def test_absolute_radial_gradient_coordinates_are_not_y_flipped(self) -> None:
        builder = RenderModelBuilder()
        builder.begin_page(500.0, 600.0)
        builder.end_page()
        brush = ET.fromstring(
            """<RadialGradientBrush xmlns=\"http://schemas.microsoft.com/xps/2005/06\"
                MappingMode=\"Absolute\"
                Center=\"250,80\"
                GradientOrigin=\"250,80\"
                RadiusX=\"50\"
                RadiusY=\"40\" />"""
        )
        x, y = _sample_brush_coordinates(brush, builder, 250.0, 80.0, None)
        self.assertAlmostEqual(x, 250.0, places=6)
        self.assertAlmostEqual(y, 80.0, places=6)

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

    def test_xps_default_path_fill_rule_is_evenodd(self) -> None:
        data = _build_xps_package()
        package = XpsPackage.from_bytes(data)
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))
        command = builder.document().pages[0].commands[0]
        self.assertIsInstance(command, PathCommand)
        self.assertEqual(command.fill_rule, "evenodd")

    def test_decode_png_dimensions(self) -> None:
        resource = decode_png(_minimal_png())
        self.assertEqual(resource.width, 1)
        self.assertEqual(resource.height, 1)

    def test_decode_png_palette_4bit(self) -> None:
        resource = decode_png(_palette_png_4bit())
        self.assertEqual(resource.width, 2)
        self.assertEqual(resource.height, 1)
        self.assertEqual(resource.data, bytes([255, 0, 0, 0, 255, 0]))
        self.assertEqual(resource.soft_mask, bytes([255, 64]))

    def test_decode_png_grayscale_1bit(self) -> None:
        resource = decode_png(_grayscale_png_1bit())
        self.assertEqual(resource.width, 2)
        self.assertEqual(resource.height, 1)
        self.assertEqual(resource.data, bytes([0, 0, 0, 255, 255, 255]))
        self.assertIsNone(resource.soft_mask)

    def test_decode_jpeg_grayscale_preserves_devicegray(self) -> None:
        resource = decode_jpeg(_grayscale_jpeg())
        self.assertEqual(resource.width, 3)
        self.assertEqual(resource.height, 2)
        self.assertEqual(resource.color_space, "DeviceGray")
        self.assertEqual(resource.filter, "DCTDecode")

    def test_parent_relative_image_brush_part_is_resolved(self) -> None:
        package = XpsPackage.from_bytes(_build_xps_package_with_parent_relative_image())
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))
        doc = builder.document()
        self.assertEqual(len(doc.pages), 1)
        self.assertEqual(len(store._images), 1)

    def test_job_media_size_points_honors_landscape_orientation(self) -> None:
        document = XpsDocument.from_bytes(_build_xps_package_with_landscape_job_print_ticket())

        media_size = _job_media_size_points(document)

        self.assertIsNotNone(media_size)
        assert media_size is not None
        self.assertAlmostEqual(media_size[0], 841.8897637795, places=6)
        self.assertAlmostEqual(media_size[1], 595.2755905512, places=6)

    def test_38976_job_landscape_ticket_keeps_landscape_page_size(self) -> None:
        document = XpsDocument.from_file("testdata/xps/integration/38976.xps")

        media_size = _job_media_size_points(document)
        render_doc, _ = _build_xps_render_document(document)

        self.assertEqual(len(render_doc.pages), 1)
        self.assertIsNotNone(media_size)
        assert media_size is not None
        self.assertAlmostEqual(media_size[0], 841.8897637795, places=6)
        self.assertAlmostEqual(media_size[1], 595.2755905512, places=6)
        self.assertAlmostEqual(render_doc.pages[0].width, 841.8897637795, places=6)
        self.assertAlmostEqual(render_doc.pages[0].height, 595.2755905512, places=6)

    def test_38976_public_outputs_keep_landscape_page_size(self) -> None:
        document = XpsDocument.from_file("testdata/xps/integration/38976.xps")

        pdf_bytes = document.to_pdf()
        page_images = document.to_images(ImageSaveOptions(format="png", dpi=300))

        match = re.search(rb"/MediaBox \[0 0 ([0-9.]+) ([0-9.]+)\]", pdf_bytes)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.group(1), b"842")
        self.assertEqual(match.group(2), b"595.5")
        self.assertEqual(len(page_images), 1)
        try:
            from PIL import Image  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on environment
            raise unittest.SkipTest("Pillow not installed") from exc
        with Image.open(BytesIO(page_images[0])) as image:
            self.assertEqual(image.size, (3507, 2480))

    def test_canvas_opacity_mask_is_rasterized_as_masked_image(self) -> None:
        package = XpsPackage.from_bytes(Path("testdata/xps/integration/canvas-opacity-mask.xps").read_bytes())
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))

        page = builder.document().pages[0]
        images = [command for command in page.commands if isinstance(command, ImageCommand)]

        self.assertTrue(images)
        masked = store.get(images[-1].image_id)
        self.assertIsNotNone(masked.soft_mask)

    def test_glyphs_opacity_mask_is_rasterized_as_masked_image(self) -> None:
        package = XpsPackage.from_bytes(Path("testdata/xps/integration/glyphs-opacity-mask.xps").read_bytes())
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))

        page = builder.document().pages[0]
        images = [command for command in page.commands if isinstance(command, ImageCommand)]

        self.assertTrue(images)
        masked = store.get(images[-1].image_id)
        self.assertIsNotNone(masked.soft_mask)

    def test_example_page1_clipped_glyphs_emit_clip_commands(self) -> None:
        package = XpsPackage.from_bytes(Path("testdata/xps/integration/example.xps").read_bytes())
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))

        page = builder.document().pages[0]
        commands = page.commands
        target_index = next(
            index
            for index, command in enumerate(commands)
            if isinstance(command, TextCommand) and command.text == "Fibers for Food Service Uniforms"
        )
        self.assertIsInstance(commands[target_index - 2], StateSaveCommand)
        self.assertIsInstance(commands[target_index - 1], ClipCommand)
        self.assertIsInstance(commands[target_index + 1], StateRestoreCommand)

    def test_language_logo_path_clip_wraps_image_brush_fill(self) -> None:
        package = XpsPackage.from_bytes(Path("testdata/xps/integration/language.xps").read_bytes())
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))

        commands = builder.document().pages[0].commands
        target_index = next(
            index
            for index, command in enumerate(commands)
            if isinstance(command, ImageCommand) and command.width == 27 and command.height == 55
        )
        self.assertIsInstance(commands[target_index - 2], StateSaveCommand)
        self.assertIsInstance(commands[target_index - 1], ClipCommand)
        self.assertIsInstance(commands[target_index + 1], StateRestoreCommand)

    def test_lineargradientbrush3_reflect_fill_is_rasterized_as_image(self) -> None:
        package = XpsPackage.from_bytes(Path("testdata/xps/integration/LinearGradientBrush_3.xps").read_bytes())
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))

        commands = builder.document().pages[0].commands
        self.assertTrue(any(isinstance(command, ImageCommand) for command in commands))

    def test_example_page1_indices_text_uses_exact_glyph_placement(self) -> None:
        package = XpsPackage.from_bytes(Path("testdata/xps/integration/example.xps").read_bytes())
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.set_package(package)
        renderer.set_current_part("/Documents/1/Pages/1.fpage")
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))

        page = builder.document().pages[0]
        run = [
            command
            for command in page.commands
            if isinstance(command, TextCommand) and command.text in set("Executive Summary")
        ]
        joined = "".join(command.text for command in run)
        self.assertIn("Executive Summary", joined)
        self.assertTrue(all(command.pdf_text_adjustments is None for command in run))

    def test_scaled_xps_path_scales_stroke_width_and_dash(self) -> None:
        data = _build_xps_package_with_scaled_dashed_path()
        package = XpsPackage.from_bytes(data)
        builder = RenderModelBuilder()
        store = XpsImageStore()
        renderer = XpsRenderer(builder, store)
        renderer.render_fixed_page(package.read("/Documents/1/Pages/1.fpage"))
        command = builder.document().pages[0].commands[0]
        self.assertIsInstance(command, PathCommand)
        self.assertIsNotNone(command.stroke)
        assert command.stroke is not None
        self.assertAlmostEqual(command.stroke.line_width, 0.75, places=6)
        self.assertEqual(command.stroke.line_cap, 0)
        self.assertEqual(command.stroke.line_join, 1)
        self.assertEqual(command.stroke.dash, [2.25, 0.75])
        self.assertAlmostEqual(command.stroke.dash_phase, 1.5, places=6)


if __name__ == "__main__":
    unittest.main()
