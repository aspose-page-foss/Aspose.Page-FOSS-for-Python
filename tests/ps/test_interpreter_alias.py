import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import PathCommand, RenderModelBuilder
from aspose.page.ps.base_ops import register_base_operators
from aspose.page.ps.graphics_ops import register_core_graphics_operators
from aspose.page.ps.interpreter import PsInterpreter
from aspose.page.ps.operators import OperatorRegistry
from aspose.page.ps.pipeline import PsConversionPipeline


class TestInterpreterOperatorAliases(unittest.TestCase):
    def test_load_defined_operator_alias_executes(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_base_operators(registry)
        register_core_graphics_operators(registry, builder)
        interpreter = PsInterpreter(registry)
        pipeline = PsConversionPipeline(interpreter, registry, builder)

        data = (
            b"%%BoundingBox: 0 0 100 100\n"
            b"/ld {load def} bind def "
            b"/m /moveto ld /l /lineto ld /cp /closepath ld /S /stroke ld\n"
            b"0 0 m 10 0 l cp S\n"
        )
        doc = pipeline.build_render_model(data)

        self.assertEqual(len(doc.pages), 1)
        self.assertEqual(len(doc.pages[0].commands), 1)
        self.assertIsInstance(doc.pages[0].commands[0], PathCommand)
        self.assertGreater(len(doc.pages[0].commands[0].path.segments), 0)


if __name__ == "__main__":
    unittest.main()
