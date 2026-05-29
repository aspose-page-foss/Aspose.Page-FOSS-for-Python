import base64
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.ps.filters import (
    ascii85_decode,
    ascii_hex_decode,
    run_length_decode,
    lzw_decode,
)
from aspose.page.ps.image_ops import register_image_operators
from aspose.page.ps.images import PsImageStore
from aspose.page.ps.objects import PsArray, PsString
from aspose.page.ps.operators import OperatorRegistry
from aspose.page.ps.pipeline import PsConversionPipeline, create_default_context
from aspose.page.common.render_model import RenderModelBuilder, ImageCommand
from aspose.page.ps.interpreter import PsInterpreter


class TestFilterDecoders(unittest.TestCase):
    def test_ascii_hex_decode(self):
        self.assertEqual(ascii_hex_decode(b"61 62 63>"), b"abc")

    def test_ascii85_decode(self):
        payload = b"hello"
        encoded = base64.a85encode(payload)
        self.assertEqual(ascii85_decode(encoded), payload)

    def test_run_length_decode(self):
        encoded = bytes([2, ord("A"), ord("B"), ord("C"), 128])
        self.assertEqual(run_length_decode(encoded), b"ABC")

    def test_lzw_decode(self):
        codes = [256, 65, 66, 257]
        packed = _pack_lzw_codes(codes)
        self.assertEqual(lzw_decode(packed), b"AB")


class TestImageOperators(unittest.TestCase):
    def test_image_operator_registers_resource(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        store = PsImageStore()
        register_image_operators(registry, builder, store)
        ctx = create_default_context()

        ctx.operand_stack.push(1)
        ctx.operand_stack.push(1)
        ctx.operand_stack.push(8)
        ctx.operand_stack.push(PsArray([1, 0, 0, 1, 0, 0]))
        ctx.operand_stack.push(PsString(b"\xff"))

        registry.get("image").fn(ctx)

        doc = builder.document()
        self.assertIsInstance(doc.pages[0].commands[0], ImageCommand)
        image_id = doc.pages[0].commands[0].image_id
        self.assertEqual(store.get(image_id).data, b"\xff")

    def test_imagemask_sets_mask(self):
        builder = RenderModelBuilder()
        builder.set_default_page_size(100, 100)
        registry = OperatorRegistry()
        store = PsImageStore()
        register_image_operators(registry, builder, store)
        ctx = create_default_context()

        ctx.operand_stack.push(1)
        ctx.operand_stack.push(1)
        ctx.operand_stack.push(True)
        ctx.operand_stack.push(PsArray([1, 0, 0, 1, 0, 0]))
        ctx.operand_stack.push(PsString(b"\xff"))

        registry.get("imagemask").fn(ctx)
        doc = builder.document()
        image_id = doc.pages[0].commands[0].image_id
        resource = store.get(image_id)
        self.assertTrue(resource.mask)
        self.assertEqual(resource.bits_per_component, 1)

    def test_pipeline_image_integration(self):
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        store = PsImageStore()
        register_image_operators(registry, builder, store)
        interpreter = PsInterpreter(registry)
        data = b"1 1 8 [1 0 0 1 0 0] <FF> image"
        pipeline = PsConversionPipeline(interpreter, registry, builder)
        doc = pipeline.build_render_model(data)
        self.assertEqual(len(doc.pages), 1)
        self.assertIsInstance(doc.pages[0].commands[0], ImageCommand)


def _pack_lzw_codes(codes):
    bit_buffer = 0
    bit_count = 0
    output = bytearray()
    for code in codes:
        bit_buffer = (bit_buffer << 9) | code
        bit_count += 9
        while bit_count >= 8:
            shift = bit_count - 8
            output.append((bit_buffer >> shift) & 0xFF)
            bit_count -= 8
            bit_buffer &= (1 << bit_count) - 1
    if bit_count:
        output.append((bit_buffer << (8 - bit_count)) & 0xFF)
    return bytes(output)


if __name__ == "__main__":
    unittest.main()
