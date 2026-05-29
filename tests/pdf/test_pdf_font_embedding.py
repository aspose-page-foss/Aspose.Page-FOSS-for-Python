import sys
from pathlib import Path
import shutil
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.common.render_model import Matrix, RenderModelBuilder
from aspose.page.pdf.writer import PdfMetadata, PdfWriter
from aspose.page.ps.font_cache import FontCache
from aspose.page.ps.fonts import FontResolver, FontResource
from aspose.page.ps.pdf_font_embed import build_embedded_font
from aspose.page.ps.base_ops import register_base_operators
from aspose.page.ps.color_ops import register_color_operators
from aspose.page.ps.graphics_ops import register_core_graphics_operators
from aspose.page.ps.image_ops import register_image_operators
from aspose.page.ps.images import PsImageStore
from aspose.page.ps.interpreter import PsInterpreter
from aspose.page.ps.operators import OperatorRegistry
from aspose.page.ps.pipeline import PsConversionPipeline
from aspose.page.ps.text_ops import register_text_operators
from aspose.page.ps.ttf_subset import has_ttf_table


class TestPdfFontEmbedding(unittest.TestCase):
    def test_embedded_font_objects_present(self) -> None:
        resources = Path(__file__).resolve().parents[2] / "resources"
        regular_src = resources / "LiberationSerif-Regular.ttf"
        if not regular_src.exists():
            self.skipTest("font resources not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            font_path = tmp / "UnitTestFont-Regular.ttf"
            shutil.copyfile(regular_src, font_path)

            cache = FontCache()
            cache.load(tmpdir)
            resolver = FontResolver(additional_fonts_folder=tmpdir, font_cache=cache)

            builder = RenderModelBuilder()
            builder.begin_page(200, 200)
            builder.add_text("Hello", "UnitTestFont", 12, Matrix.identity(), None)
            builder.end_page()
            doc = builder.document()

            metadata = PdfMetadata(
                title="",
                creator="",
                producer="Aspose.Page FOSS for Python",
                creation_date="D:20260101000000",
                mod_date="D:20260101000000",
                trapped=False,
            )

            def font_provider(font_name: str, used_codes: set[int]):
                return build_embedded_font(font_name, used_codes, resolver)

            writer = PdfWriter(metadata, no_compression=True, font_provider=font_provider)
            pdf = writer.write(doc)

            self.assertIn(b"/FontFile2", pdf)
            self.assertIn(b"/ToUnicode", pdf)
            self.assertIn(b"+UnitTestFont", pdf)

    def test_embeds_defined_type42_font_program(self) -> None:
        resources = Path(__file__).resolve().parents[2] / "resources"
        regular_src = resources / "LiberationSerif-Regular.ttf"
        if not regular_src.exists():
            self.skipTest("font resources not available")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            font_path = tmp / "DefinedType42.ttf"
            shutil.copyfile(regular_src, font_path)

            cache = FontCache()
            cache.load(tmpdir)
            resolver = FontResolver(additional_fonts_folder=tmpdir, font_cache=cache)
            metrics = cache.metrics_for(font_path)
            data = font_path.read_bytes()
            resolver.register_defined_font(
                "f-0-0",
                FontResource(
                    name="f-0-0",
                    font_type="Type42",
                    units_per_em=metrics.units_per_em,
                    encoding={},
                    glyph_widths={},
                    substitute=False,
                    code_widths=metrics.code_widths,
                    font_program=data,
                ),
            )

            builder = RenderModelBuilder()
            builder.begin_page(200, 200)
            builder.add_text("AXISPOINT", "f-0-0", 12, Matrix.identity(), None)
            builder.end_page()
            doc = builder.document()

            metadata = PdfMetadata(
                title="",
                creator="",
                producer="Aspose.Page FOSS for Python",
                creation_date="D:20260101000000",
                mod_date="D:20260101000000",
                trapped=False,
            )

            def font_provider(font_name: str, used_codes: set[int]):
                return build_embedded_font(font_name, used_codes, resolver)

            writer = PdfWriter(metadata, no_compression=True, font_provider=font_provider)
            pdf = writer.write(doc)

            self.assertIn(b"/FontFile2", pdf)
            self.assertIn(b"+f-0-0", pdf)

    def test_embeds_type42_without_cmap_by_synthesized_cmap(self) -> None:
        sample = Path(__file__).resolve().parents[2] / "testdata/ps/functional/FONTS10/TrueType.ps"
        if not sample.exists():
            self.skipTest("sample Type42 PS not available")

        resolver = FontResolver(additional_fonts_folder="testdata/ps/necessary_fonts")
        builder = RenderModelBuilder()
        registry = OperatorRegistry()
        image_store = PsImageStore()
        register_base_operators(registry)
        register_core_graphics_operators(registry, builder)
        register_color_operators(registry, builder)
        register_image_operators(registry, builder, image_store)
        register_text_operators(registry, builder, resolver)
        interpreter = PsInterpreter(registry)
        pipeline = PsConversionPipeline(
            interpreter,
            registry,
            builder,
            font_resolver=resolver,
            image_store=image_store,
        )
        doc = pipeline.build_render_model(sample.read_bytes())
        used_codes: dict[str, set[int]] = {}
        for page in doc.pages:
            for command in page.commands:
                if hasattr(command, "font_ref") and hasattr(command, "text"):
                    used_codes.setdefault(command.font_ref, set()).update(ord(ch) for ch in command.text)
        self.assertIn("f-0-0", used_codes)

        embedded = build_embedded_font("f-0-0", used_codes["f-0-0"], resolver)
        self.assertIsNotNone(embedded)
        assert embedded is not None
        self.assertGreater(len(embedded.font_file), 0)
        self.assertIn(ord("A"), embedded.char_code_map)
        self.assertTrue(has_ttf_table(embedded.font_file, b"cmap"))


if __name__ == "__main__":
    unittest.main()
