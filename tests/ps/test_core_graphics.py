import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import PathCommand, Point
from aspose.page.ps.document import PsDocument
from aspose.page.ps.base_ops import register_base_operators
from aspose.page.ps.graphics_ops import register_core_graphics_operators
from aspose.page.ps.operators import OperatorRegistry
from aspose.page.ps.pipeline import PsConversionPipeline, create_default_context
from aspose.page.ps.interpreter import PsInterpreter
from aspose.page.common.render_model import RenderModelBuilder


class TestPsDocument(unittest.TestCase):
    def test_eps_detection_from_bytes(self):
        data = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n"
        doc = PsDocument.from_bytes(data)
        self.assertTrue(doc.is_eps)
        self.assertIsNotNone(doc.dsc)


class TestCoreGraphicsOperators(unittest.TestCase):
    def setUp(self):
        self.builder = RenderModelBuilder()
        self.builder.set_default_page_size(200, 100)
        self.registry = OperatorRegistry()
        register_core_graphics_operators(self.registry, self.builder)
        self.ctx = create_default_context()
        self.ctx.default_page_size = (200, 100)

    def _call(self, name):
        entry = self.registry.get(name)
        self.assertIsNotNone(entry)
        entry.fn(self.ctx)

    def test_moveto_lineto_closepath_stroke(self):
        self.ctx.operand_stack.push(0)
        self.ctx.operand_stack.push(0)
        self._call("moveto")
        self.ctx.operand_stack.push(10)
        self.ctx.operand_stack.push(0)
        self._call("lineto")
        self._call("closepath")
        self._call("stroke")
        doc = self.builder.document()
        self.assertEqual(len(doc.pages), 1)
        command = doc.pages[0].commands[0]
        self.assertIsInstance(command, PathCommand)
        self.assertEqual(command.path.segments[0].kind, "move")
        self.assertEqual(command.path.segments[-1].kind, "close")

    def test_rectpath_segments(self):
        self.ctx.operand_stack.push(1)
        self.ctx.operand_stack.push(2)
        self.ctx.operand_stack.push(3)
        self.ctx.operand_stack.push(4)
        self._call("rectpath")
        path = self.ctx.graphics_state_stack.peek().current_path
        self.assertEqual(len(path.segments), 5)

    def test_translate_applies_ctm(self):
        self.ctx.operand_stack.push(5)
        self.ctx.operand_stack.push(7)
        self._call("translate")
        self.ctx.operand_stack.push(1)
        self.ctx.operand_stack.push(1)
        self._call("moveto")
        path = self.ctx.graphics_state_stack.peek().current_path
        point = path.segments[0].points[0]
        self.assertEqual(point, Point(6.0, 8.0))

    def test_initclip_emits_clip_command(self):
        self._call("initclip")
        doc = self.builder.document()
        self.assertEqual(len(doc.pages), 1)
        self.assertEqual(doc.pages[0].commands[0].__class__.__name__, "ClipCommand")

    def test_save_restore_round_trip(self):
        self.ctx.operand_stack.push(2)
        self._call("setlinewidth")
        self._call("save")
        self.ctx.operand_stack.push(5)
        self._call("setlinewidth")
        self._call("restore")
        state = self.ctx.graphics_state_stack.peek()
        self.assertEqual(state.line_width, 2.0)


class TestCoreGraphicsIntegration(unittest.TestCase):
    def test_pipeline_with_core_ops(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_core_graphics_operators(registry, builder)
        interpreter = PsInterpreter(registry)
        data = b"0 0 moveto 10 0 lineto stroke"
        pipeline = PsConversionPipeline(interpreter, registry, builder)
        doc = pipeline.build_render_model(data)
        self.assertEqual(len(doc.pages), 1)
        self.assertIsInstance(doc.pages[0].commands[0], PathCommand)

    def test_concat_matrix_executes_named_value(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_base_operators(registry)
        register_core_graphics_operators(registry, builder)
        interpreter = PsInterpreter(registry)
        data = (
            b"/x_squash { 30 cos } def "
            b"[ x_squash 0 0 1 0 0 ] concat "
            b"0 0 moveto 1 0 lineto stroke"
        )
        pipeline = PsConversionPipeline(interpreter, registry, builder)
        doc = pipeline.build_render_model(data)
        command = doc.pages[0].commands[0]
        line_end = command.path.segments[1].points[0]
        self.assertAlmostEqual(line_end.x, 0.8660254, places=6)
        self.assertAlmostEqual(line_end.y, 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
