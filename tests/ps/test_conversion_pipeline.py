import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import (
    Paint,
    Path,
    PathSegment,
    Point,
    Rect,
    RenderModelBuilder,
    StrokeStyle,
    rect_path,
)
from aspose.page.ps.dsc import DscMetadata
from aspose.page.ps.interpreter import PsInterpreter
from aspose.page.ps.operators import OperatorRegistry
from aspose.page.ps.pipeline import (
    PsConversionPipeline,
    default_page_size_from_dsc,
)


class TestRenderModel(unittest.TestCase):
    def test_rect_path_segments(self):
        rect = Rect(0, 0, 10, 20)
        path = rect_path(rect)
        self.assertEqual(len(path.segments), 5)
        self.assertEqual(path.segments[0].kind, "move")
        self.assertEqual(path.segments[-1].kind, "close")
        self.assertEqual(path.segments[0].points[0], Point(0, 0))
        self.assertEqual(path.segments[2].points[0], Point(10, 20))

    def test_builder_auto_page(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 200)
        path = rect_path(Rect(0, 0, 1, 1))
        builder.add_path(path, None, None)
        doc = builder.document()
        self.assertEqual(len(doc.pages), 1)
        self.assertEqual(doc.pages[0].width, 100)
        self.assertEqual(doc.pages[0].height, 200)

    def test_end_page_without_active(self):
        builder = RenderModelBuilder()
        with self.assertRaises(ValueError):
            builder.end_page()


class TestPipelineHelpers(unittest.TestCase):
    def test_default_page_size_from_dsc(self):
        dsc = DscMetadata(bounding_box=(0, 0, 200, 300))
        size = default_page_size_from_dsc(dsc)
        self.assertEqual(size, (200.0, 300.0))

        dsc = DscMetadata(hires_bounding_box=(1.0, 2.0, 5.0, 8.0))
        size = default_page_size_from_dsc(dsc)
        self.assertEqual(size, (4.0, 6.0))

        dsc = DscMetadata(
            bounding_box=(36, 61, 577, 757),
            document_media_size=(612.0, 792.0),
        )
        size = default_page_size_from_dsc(dsc)
        self.assertEqual(size, (612.0, 792.0))

        size = default_page_size_from_dsc(None)
        self.assertEqual(size, (595.0, 842.0))


class TestPipelineIntegration(unittest.TestCase):
    def test_pipeline_records_commands(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        interpreter = PsInterpreter(registry)

        def op_draw(ctx):
            path = Path(
                [
                    PathSegment("move", [Point(0, 0)]),
                    PathSegment("line", [Point(1, 0)]),
                    PathSegment("close", []),
                ]
            )
            stroke = StrokeStyle(1.0, 0, 0, 10.0, [], 0.0)
            paint = Paint("DeviceRGB", (0, 0, 0))
            builder.add_path(path, stroke, paint)

        registry.register("draw", op_draw)

        data = b"%%BoundingBox: 0 0 200 300\n draw"
        pipeline = PsConversionPipeline(interpreter, registry, builder)
        doc = pipeline.build_render_model(data)
        self.assertEqual(len(doc.pages), 1)
        self.assertEqual(doc.pages[0].width, 200.0)
        self.assertEqual(doc.pages[0].height, 300.0)
        self.assertEqual(len(doc.pages[0].commands), 1)


if __name__ == "__main__":
    unittest.main()
