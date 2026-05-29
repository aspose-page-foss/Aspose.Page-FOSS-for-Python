import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.color_resources import ExponentialFunction, SampledFunction, StitchingFunction
from aspose.page.common.render_model import PathCommand, RenderModelBuilder
from aspose.page.ps.color_ops import register_color_operators
from aspose.page.ps.color_spaces import load_default_icc_profile
from aspose.page.ps.graphics_ops import register_core_graphics_operators
from aspose.page.ps.interpreter import PsInterpreter
from aspose.page.ps.objects import PsArray, PsDict, PsName, PsProcedure, PsString
from aspose.page.ps.operators import OperatorRegistry
from aspose.page.ps.pipeline import PsConversionPipeline, create_default_context


class TestColorOperators(unittest.TestCase):
    def test_setrgbcolor_updates_paints(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_color_operators(registry, builder)
        ctx = create_default_context()

        ctx.operand_stack.push(0.1)
        ctx.operand_stack.push(0.2)
        ctx.operand_stack.push(0.3)
        registry.get("setrgbcolor").fn(ctx)

        state = ctx.graphics_state_stack.peek()
        self.assertEqual(state.stroke_paint.kind, "DeviceRGB")
        self.assertEqual(state.fill_paint.kind, "DeviceRGB")

    def test_indexed_colorspace_registers_resource(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_color_operators(registry, builder)
        ctx = create_default_context()

        space = PsArray(
            [
                PsName("Indexed"),
                PsName("DeviceRGB"),
                1,
                PsString(b"\x00\x00\x00\xff\x00\x00"),
            ]
        )
        ctx.operand_stack.push(space)
        registry.get("setcolorspace").fn(ctx)
        ctx.operand_stack.push(1)
        registry.get("setcolor").fn(ctx)

        state = ctx.graphics_state_stack.peek()
        self.assertEqual(state.fill_paint.kind, "DeviceRGB")
        self.assertTrue(builder.document().resources.color_spaces)

    def test_devicen_setcolor(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_color_operators(registry, builder)
        ctx = create_default_context()

        func = PsDict(
            {
                "FunctionType": 2,
                "Domain": PsArray([0, 1]),
                "Range": PsArray([0, 1, 0, 1, 0, 1]),
                "C0": PsArray([0, 0, 0]),
                "C1": PsArray([1, 1, 1]),
                "N": 1,
            }
        )
        space = PsArray(
            [
                PsName("DeviceN"),
                PsArray([PsName("Cyan"), PsName("Magenta")]),
                PsName("DeviceRGB"),
                func,
            ]
        )
        ctx.operand_stack.push(space)
        registry.get("setcolorspace").fn(ctx)
        ctx.operand_stack.push(0.2)
        ctx.operand_stack.push(0.7)
        registry.get("setcolor").fn(ctx)
        self.assertEqual(ctx.graphics_state_stack.peek().fill_paint.kind, "DeviceRGB")

    def test_makepattern_registers_pattern(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_core_graphics_operators(registry, builder)
        register_color_operators(registry, builder)
        ctx = create_default_context()

        proc = PsProcedure([0, 0, PsName("moveto")])
        pattern_dict = PsDict(
            {
                "PatternType": 1,
                "PaintType": 1,
                "TilingType": 1,
                "BBox": PsArray([0, 0, 10, 10]),
                "XStep": 10,
                "YStep": 10,
                "PaintProc": proc,
            }
        )
        ctx.operand_stack.push(pattern_dict)
        ctx.operand_stack.push(PsArray([1, 0, 0, 1, 0, 0]))
        registry.get("makepattern").fn(ctx)

        pattern = ctx.operand_stack.pop()
        self.assertEqual(pattern.pattern_id[:1], "P")
        self.assertTrue(builder.document().resources.patterns)

    def test_shfill_emits_pattern_paint(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_color_operators(registry, builder)
        ctx = create_default_context()
        ctx.default_page_size = (100, 100)

        func = PsDict(
            {
                "FunctionType": 2,
                "Domain": PsArray([0, 1]),
                "Range": PsArray([0, 1, 0, 1, 0, 1]),
                "C0": PsArray([0, 0, 0]),
                "C1": PsArray([1, 1, 1]),
                "N": 1,
            }
        )
        shading = PsDict(
            {
                "ShadingType": 2,
                "ColorSpace": PsName("DeviceRGB"),
                "Coords": PsArray([0, 0, 10, 0]),
                "Function": func,
                "Extend": PsArray([True, True]),
            }
        )
        ctx.operand_stack.push(shading)
        registry.get("shfill").fn(ctx)

        doc = builder.document()
        self.assertTrue(doc.pages[0].commands)
        self.assertEqual(doc.pages[0].commands[0].fill.kind, "Pattern")

    def test_functions_evaluate_within_range(self):
        sampled = SampledFunction(
            domain=[0.0, 1.0],
            range=[0.0, 1.0],
            size=[2],
            bits_per_sample=8,
            order=1,
            encode=[0.0, 1.0],
            decode=[0.0, 1.0],
            samples=b"\x00\xff",
        )
        self.assertTrue(0.0 <= sampled.evaluate([0.5])[0] <= 1.0)

        exp = ExponentialFunction(
            domain=[0.0, 1.0],
            range=[0.0, 1.0],
            c0=[0.0],
            c1=[1.0],
            n=1.0,
        )
        self.assertTrue(0.0 <= exp.evaluate([0.5])[0] <= 1.0)

        stitch = StitchingFunction(
            domain=[0.0, 1.0],
            range=[0.0, 1.0],
            functions=[exp, exp],
            bounds=[0.5],
            encode=[0.0, 1.0, 0.0, 1.0],
        )
        self.assertTrue(0.0 <= stitch.evaluate([0.25])[0] <= 1.0)

    def test_load_default_icc_profile(self):
        data = load_default_icc_profile()
        self.assertGreater(len(data), 0)

    def test_setcolorspace_accepts_separation_name_string(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_color_operators(registry, builder)
        ctx = create_default_context()

        func = PsDict(
            {
                "FunctionType": 2,
                "Domain": PsArray([0, 1]),
                "Range": PsArray([0, 1, 0, 1, 0, 1, 0, 1]),
                "C0": PsArray([0, 0, 0, 0]),
                "C1": PsArray([0, 1, 0, 0]),
                "N": 1,
            }
        )
        space = PsArray(
            [
                PsName("Separation"),
                PsString(b"Magenta"),
                PsName("DeviceCMYK"),
                func,
            ]
        )
        ctx.operand_stack.push(space)
        registry.get("setcolorspace").fn(ctx)

        state = ctx.graphics_state_stack.peek()
        self.assertEqual(getattr(state.current_color_space, "name", None), "Magenta")

    def test_setcolorspace_accepts_procedure_tint_transform(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_color_operators(registry, builder)
        ctx = create_default_context()

        space = PsArray(
            [
                PsName("Separation"),
                PsString(b"Magenta"),
                PsName("DeviceCMYK"),
                PsProcedure([0.0, PsName("exch"), 0.0, 0.0]),
            ]
        )
        ctx.operand_stack.push(space)
        registry.get("setcolorspace").fn(ctx)
        ctx.operand_stack.push(0.5)
        registry.get("setcolor").fn(ctx)

        state = ctx.graphics_state_stack.peek()
        self.assertEqual(state.fill_paint.kind, "DeviceCMYK")
        self.assertTrue(builder.document().resources.functions)

    def test_setcolorspace_resolves_named_ciebased_dictionary(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_color_operators(registry, builder)
        ctx = create_default_context()

        cie_dict = PsDict({"N": 3})
        ctx.dictionary_stack.peek().items["CIEColors"] = cie_dict
        ctx.operand_stack.push(PsArray([PsName("CIEBasedABC", literal=True), PsName("CIEColors")]))
        registry.get("setcolorspace").fn(ctx)

        self.assertEqual(ctx.graphics_state_stack.peek().current_color_space.components, 3)

    def test_ciebased_setcolor_uses_declared_ranges(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_color_operators(registry, builder)
        ctx = create_default_context()

        cie_dict = PsDict({"RangeABC": PsArray([0, 2, 0, 4, 0, 8])})
        ctx.operand_stack.push(PsArray([PsName("CIEBasedABC", literal=True), cie_dict]))
        registry.get("setcolorspace").fn(ctx)
        ctx.operand_stack.push(1)
        ctx.operand_stack.push(2)
        ctx.operand_stack.push(4)
        registry.get("setcolor").fn(ctx)

        self.assertEqual(ctx.graphics_state_stack.peek().fill_paint.kind, "DeviceRGB")
        self.assertEqual(ctx.graphics_state_stack.peek().fill_paint.value, (0.5, 0.5, 0.5))

    def test_sethsbcolor_normalizes_components(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_color_operators(registry, builder)
        ctx = create_default_context()

        ctx.operand_stack.push(1.2)   # hue wraps to 0.2
        ctx.operand_stack.push(2.0)   # saturation clamps to 1.0
        ctx.operand_stack.push(-0.5)  # brightness clamps to 0.0
        registry.get("sethsbcolor").fn(ctx)

        state = ctx.graphics_state_stack.peek()
        self.assertEqual(state.current_color_space.name, "DeviceRGB")
        self.assertEqual(state.current_color_components, (0.0, 0.0, 0.0))

    def test_overprint_state_is_emitted_to_path_command(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        register_core_graphics_operators(registry, builder)
        register_color_operators(registry, builder)
        ctx = create_default_context()
        ctx.default_page_size = (100, 100)

        ctx.operand_stack.push(True)
        registry.get("setoverprint").fn(ctx)

        ctx.operand_stack.push(0.0)
        registry.get("setgray").fn(ctx)
        ctx.operand_stack.push(0)
        ctx.operand_stack.push(0)
        registry.get("moveto").fn(ctx)
        ctx.operand_stack.push(10)
        ctx.operand_stack.push(0)
        registry.get("lineto").fn(ctx)
        ctx.operand_stack.push(10)
        ctx.operand_stack.push(10)
        registry.get("lineto").fn(ctx)
        registry.get("closepath").fn(ctx)
        registry.get("fill").fn(ctx)

        command = builder.document().pages[0].commands[0]
        self.assertIsInstance(command, PathCommand)
        self.assertTrue(command.overprint)


class TestColorIntegration(unittest.TestCase):
    def test_pipeline_indexed_color(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        register_core_graphics_operators(registry, builder)
        register_color_operators(registry, builder)
        interpreter = PsInterpreter(registry)
        data = (
            b"[/Indexed /DeviceRGB 1 <000000 ff0000>] setcolorspace "
            b"1 setcolor newpath 0 0 moveto 10 0 lineto 10 10 lineto closepath fill"
        )
        pipeline = PsConversionPipeline(interpreter, registry, builder)
        doc = pipeline.build_render_model(data)
        self.assertTrue(doc.resources.color_spaces)


if __name__ == "__main__":
    unittest.main()
