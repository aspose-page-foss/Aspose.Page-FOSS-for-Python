import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import PathCommand, TextCommand, RenderModelBuilder
from aspose.page.ps.fonts import FontResolver, FontResource
from aspose.page.ps.graphics_ops import register_core_graphics_operators
from aspose.page.ps.operators import OperatorRegistry
from aspose.page.ps.pipeline import PsConversionPipeline, create_default_context
from aspose.page.ps.interpreter import PsInterpreter
from aspose.page.ps.text_ops import register_text_operators
from aspose.page.ps.objects import PsArray, PsName, PsOperator, PsProcedure, PsString


class TestTextOperators(unittest.TestCase):
    def test_show_emits_text_command(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        ctx.operand_stack.push(PsName("Helvetica"))
        ctx.operand_stack.push(12)
        registry.get("selectfont").fn(ctx)

        ctx.operand_stack.push(PsString(b"Hi"))
        registry.get("show").fn(ctx)

        doc = builder.document()
        self.assertIsInstance(doc.pages[0].commands[0], TextCommand)

    def test_xshow_splits_text(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        ctx.operand_stack.push(PsName("Helvetica"))
        ctx.operand_stack.push(12)
        registry.get("selectfont").fn(ctx)

        ctx.operand_stack.push(PsString(b"AB"))
        ctx.operand_stack.push(PsArray([1, 1]))
        registry.get("xshow").fn(ctx)

        doc = builder.document()
        self.assertEqual(len(doc.pages[0].commands), 2)

    def test_missing_font_fallback(self):
        resolver = FontResolver()
        font = resolver.resolve("MissingFont")
        self.assertTrue(font.substitute)
        self.assertTrue(font.glyph_widths)

    def test_widthshow_advances_text(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        ctx.operand_stack.push(PsName("Helvetica"))
        ctx.operand_stack.push(12)
        registry.get("selectfont").fn(ctx)

        ctx.operand_stack.push(PsString(b"AA"))
        registry.get("stringwidth").fn(ctx)
        _ = ctx.operand_stack.pop()
        base_width = ctx.operand_stack.pop()

        ctx.graphics_state_stack.peek().text_matrix = (1, 0, 0, 1, 0, 0)
        ctx.operand_stack.push(PsString(b"AA"))
        ctx.operand_stack.push(2.0)
        ctx.operand_stack.push(0.0)
        ctx.operand_stack.push(PsString(b"A"))
        registry.get("widthshow").fn(ctx)

        advance = ctx.graphics_state_stack.peek().text_matrix[4]
        self.assertAlmostEqual(advance, base_width + 4.0, places=4)

    def test_show_advances_with_scaled_text_matrix(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        ctx.operand_stack.push(PsName("Helvetica"))
        ctx.operand_stack.push(12)
        registry.get("selectfont").fn(ctx)

        ctx.operand_stack.push(PsString(b"A"))
        registry.get("stringwidth").fn(ctx)
        _ = ctx.operand_stack.pop()
        base_width = ctx.operand_stack.pop()

        ctx.graphics_state_stack.peek().text_matrix = (2, 0, 0, 2, 0, 0)
        ctx.operand_stack.push(PsString(b"A"))
        registry.get("show").fn(ctx)

        advance = ctx.graphics_state_stack.peek().text_matrix[4]
        self.assertAlmostEqual(advance, base_width * 2.0, places=4)

    def test_awidthshow_advances_text(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        ctx.operand_stack.push(PsName("Helvetica"))
        ctx.operand_stack.push(12)
        registry.get("selectfont").fn(ctx)

        ctx.graphics_state_stack.peek().text_matrix = (1, 0, 0, 1, 0, 0)
        ctx.operand_stack.push(PsString(b"A"))
        ctx.operand_stack.push(1.0)
        ctx.operand_stack.push(0.0)
        ctx.operand_stack.push(PsString(b"A"))
        ctx.operand_stack.push(2.0)
        ctx.operand_stack.push(0.0)
        registry.get("awidthshow").fn(ctx)

        advance = ctx.graphics_state_stack.peek().text_matrix[4]
        self.assertGreater(advance, 0.0)

    def test_type3_charproc_emits_path(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_core_graphics_operators(registry, builder)
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        proc = PsProcedure(
            [
                0, 0, PsOperator("moveto"),
                10, 0, PsOperator("lineto"),
                10, 10, PsOperator("lineto"),
                0, 10, PsOperator("lineto"),
                PsOperator("closepath"),
                PsOperator("fill"),
            ]
        )
        font = FontResource(
            "Type3Font",
            "Type3",
            1000,
            {65: "A"},
            {},
            False,
            char_procs={"A": proc},
        )
        ctx.graphics_state_stack.peek().font = font
        ctx.graphics_state_stack.peek().font_size = 12

        ctx.operand_stack.push(PsString(b"A"))
        registry.get("show").fn(ctx)

        doc = builder.document()
        self.assertTrue(any(isinstance(cmd, PathCommand) for cmd in doc.pages[0].commands))

    def test_charpath_appends_segments(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_core_graphics_operators(registry, builder)
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        proc = PsProcedure(
            [
                0, 0, PsOperator("moveto"),
                5, 0, PsOperator("lineto"),
                5, 5, PsOperator("lineto"),
                0, 5, PsOperator("lineto"),
                PsOperator("closepath"),
                PsOperator("fill"),
            ]
        )
        font = FontResource(
            "Type3Font",
            "Type3",
            1000,
            {65: "A"},
            {},
            False,
            char_procs={"A": proc},
        )
        ctx.graphics_state_stack.peek().font = font
        ctx.graphics_state_stack.peek().font_size = 12

        ctx.operand_stack.push(PsString(b"A"))
        ctx.operand_stack.push(True)
        registry.get("charpath").fn(ctx)

        self.assertGreater(len(ctx.graphics_state_stack.peek().current_path.segments), 0)

    def test_type0_fmaptype2_maps_selector_and_char_bytes(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        empty_descendant = FontResource(
            name="EmptyFont",
            font_type="Type3",
            units_per_em=1000,
            encoding={},
            glyph_widths={},
            substitute=False,
            char_procs={},
            code_widths={},
        )
        cards_descendant = FontResource(
            name="Helvetica",
            font_type="Type1",
            units_per_em=1000,
            encoding={65: "A"},
            glyph_widths={"A": 600.0},
            substitute=False,
            code_widths={65: 600.0},
        )
        fmap = [0] * 256
        fmap[ord("C")] = 1
        composite = FontResource(
            name="Playing-Cards",
            font_type="Type0",
            units_per_em=1000,
            encoding={65: "A"},
            glyph_widths={"A": 600.0},
            substitute=False,
            descendant=cards_descendant,
            fdep_vector=[empty_descendant, cards_descendant],
            fmap_encoding=fmap,
            fmap_type=2,
        )
        ctx.graphics_state_stack.peek().font = composite
        ctx.graphics_state_stack.peek().font_size = 12

        ctx.operand_stack.push(PsString(b"CA"))
        registry.get("show").fn(ctx)

        doc = builder.document()
        text_commands = [cmd for cmd in doc.pages[0].commands if isinstance(cmd, TextCommand)]
        self.assertEqual(len(text_commands), 1)
        self.assertEqual(text_commands[0].text, "A")
        self.assertEqual(text_commands[0].font_ref, "Helvetica")

    def test_xshow_full_array_uses_explicit_advances(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        ctx.operand_stack.push(PsName("Helvetica"))
        ctx.operand_stack.push(12)
        registry.get("selectfont").fn(ctx)

        ctx.operand_stack.push(PsString(b"AB"))
        ctx.operand_stack.push(PsArray([100.0, 200.0]))
        registry.get("xshow").fn(ctx)

        self.assertAlmostEqual(ctx.graphics_state_stack.peek().text_matrix[4], 300.0, places=6)

    def test_show_respects_font_encoding_reencode(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_text_operators(registry, builder, FontResolver())
        ctx = create_default_context()

        font = FontResource(
            name="ReencodedFont",
            font_type="Type1",
            units_per_em=1000,
            encoding={ord("P"): "K", ord("o"): "l", ord("!"): "exclam"},
            glyph_widths={"K": 500.0, "l": 500.0, "exclam": 500.0},
            substitute=False,
            code_widths={ord("P"): 500.0, ord("o"): 500.0, ord("!"): 500.0},
        )
        ctx.graphics_state_stack.peek().font = font
        ctx.graphics_state_stack.peek().font_size = 12

        ctx.operand_stack.push(PsString(b"Po!"))
        registry.get("show").fn(ctx)

        doc = builder.document()
        text_commands = [cmd for cmd in doc.pages[0].commands if isinstance(cmd, TextCommand)]
        self.assertEqual(len(text_commands), 1)
        self.assertEqual(text_commands[0].text, "Kl!")


class TestTextIntegration(unittest.TestCase):
    def test_pipeline_show_text(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_text_operators(registry, builder, FontResolver())
        interpreter = PsInterpreter(registry)
        data = b"/Helvetica 12 selectfont (Hi) show"
        pipeline = PsConversionPipeline(interpreter, registry, builder)
        doc = pipeline.build_render_model(data)
        self.assertEqual(len(doc.pages), 1)
        self.assertIsInstance(doc.pages[0].commands[0], TextCommand)


if __name__ == "__main__":
    unittest.main()
