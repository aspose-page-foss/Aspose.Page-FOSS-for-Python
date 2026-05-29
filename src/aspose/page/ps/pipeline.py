"""PS/EPS conversion pipeline to render model."""

from __future__ import annotations

import re

from .context import ExecutionContext, GraphicsState
from .dsc import DscMetadata, parse_dsc_comments
from .encodings import (
    ISO_LATIN1_ENCODING,
    STANDARD_ENCODING,
    SYMBOL_ENCODING,
    ZAPF_DINGBATS_ENCODING,
)
from .page_geometry import page_size_from_dsc
from .interpreter import PsInterpreter
from .objects import PsArray, PsDict, PsName, PsOperator, PsString
from .operators import OperatorRegistry
from .stack import PsStack
from .images import PsImageStore
from .fonts import FontResolver, FontResource
from .type1_parser import parse_type1_resource_block
from ..common.render_model import RenderDocument, RenderModelBuilder


def default_page_size_from_dsc(dsc: DscMetadata | None) -> tuple[float, float]:
    """Backward-compatible wrapper for page size derivation."""
    return page_size_from_dsc(dsc)


def _is_eps_document(data: bytes) -> bool:
    if not data:
        return False
    head = data[:2048].decode("latin-1", errors="ignore")
    first_line = head.splitlines()[0] if head else ""
    return first_line.startswith("%!PS-Adobe-") and "EPSF" in first_line


_TYPE1_RESOURCE_RE = re.compile(
    rb"%%BeginResource:\s*font\s*\([^\r\n)]*\).*?%%EndResource",
    re.DOTALL,
)


def _bbox_origin_from_dsc(dsc: DscMetadata | None) -> tuple[float, float] | None:
    if dsc is None:
        return None
    if dsc.crop_box is not None or dsc.document_media_size is not None:
        return None
    if dsc.hires_bounding_box is not None:
        return float(dsc.hires_bounding_box[0]), float(dsc.hires_bounding_box[1])
    if dsc.bounding_box is not None:
        return float(dsc.bounding_box[0]), float(dsc.bounding_box[1])
    return None


def preprocess_type1_resources(data: bytes) -> bytes:
    """Strip embedded Type1 resource blocks that rely on `currentfile eexec`."""
    chunks: list[bytes] = []
    cursor = 0
    for match in _TYPE1_RESOURCE_RE.finditer(data):
        block = match.group(0)
        if b"/FontType 1" not in block or b"currentfile eexec" not in block:
            continue
        chunks.append(data[cursor:match.start()])
        chunks.append(b"\n")
        cursor = match.end()
    chunks.append(data[cursor:])
    return b"".join(chunks)


def _register_embedded_type1_resources(data: bytes, resolver: FontResolver | None) -> None:
    if resolver is None:
        return
    for match in _TYPE1_RESOURCE_RE.finditer(data):
        block = match.group(0)
        metrics = parse_type1_resource_block(block)
        if metrics is None:
            continue
        resource = FontResource(
            name=metrics.font_name,
            font_type="Type1",
            units_per_em=metrics.units_per_em,
            encoding=metrics.encoding,
            glyph_widths=metrics.glyph_widths,
            substitute=False,
            code_widths=metrics.code_widths,
            font_program=metrics.font_program_type1,
        )
        resolver.register_defined_font(metrics.font_name, resource)


def create_default_context(
    font_resolver: FontResolver | None = None,
    image_store: PsImageStore | None = None,
) -> ExecutionContext:
    """Create a default interpreter execution context.

    Example:
        >>> ctx = create_default_context()
        >>> ctx.userdict is not None
        True
    """
    systemdict = PsDict({})
    userdict = PsDict({})
    globaldict = PsDict({})
    font_directory = PsDict({})
    statusdict = PsDict({})
    errordict = PsDict({})
    systemdict.items.update(
        {
            "true": True,
            "false": False,
            "null": None,
            "languagelevel": 3,
            "userdict": userdict,
            "globaldict": globaldict,
            "systemdict": systemdict,
            "statusdict": statusdict,
            "errordict": errordict,
            "$error": PsDict({}),
            "FontDirectory": font_directory,
            "version": PsString(b"3017"),
            "product": PsString(b"Aspose.Page FOSS"),
            "setglobal": PsOperator("setglobal"),
            "currentglobal": PsOperator("currentglobal"),
            "setuserparams": PsOperator("setuserparams"),
            "setpacking": PsOperator("setpacking"),
            "currentpacking": PsOperator("currentpacking"),
            "StandardEncoding": _build_encoding_array(STANDARD_ENCODING),
            "ISOLatin1Encoding": _build_encoding_array(ISO_LATIN1_ENCODING),
            "ISOLatin1": _build_encoding_array(ISO_LATIN1_ENCODING),
            "SymbolEncoding": _build_encoding_array(SYMBOL_ENCODING),
            "ZapfDingbatsEncoding": _build_encoding_array(ZAPF_DINGBATS_ENCODING),
        }
    )
    dict_stack = PsStack([systemdict, userdict])
    return ExecutionContext(
        operand_stack=PsStack(),
        execution_stack=PsStack(),
        dictionary_stack=dict_stack,
        graphics_state_stack=PsStack([GraphicsState()]),
        userdict=userdict,
        systemdict=systemdict,
        image_store=image_store or PsImageStore(),
        font_resolver=font_resolver or FontResolver(),
    )


def _build_encoding_array(mapping: dict[int, str]) -> PsArray:
    values = [PsName(".notdef", literal=True) for _ in range(256)]
    for code, name in mapping.items():
        if 0 <= code < 256:
            values[code] = PsName(name, literal=True)
    return PsArray(values)


class PsConversionPipeline:
    """Convert PS/EPS byte streams into render model documents.

    Example:
        >>> builder = RenderModelBuilder()
        >>> pipeline = PsConversionPipeline(PsInterpreter(OperatorRegistry()), OperatorRegistry(), builder)
        >>> doc = pipeline.build_render_model(b\"%BoundingBox: 0 0 10 10\\n\")
        >>> isinstance(doc.pages, list)
        True
    """

    def __init__(
        self,
        interpreter: PsInterpreter,
        operators: OperatorRegistry,
        builder: RenderModelBuilder,
        font_resolver: FontResolver | None = None,
        image_store: PsImageStore | None = None,
    ) -> None:
        self._interpreter = interpreter
        self._operators = operators
        self._builder = builder
        self._font_resolver = font_resolver
        self._image_store = image_store

    def build_render_model(self, data: bytes) -> RenderDocument:
        """Parse PS/EPS bytes and return a render document."""
        ctx = create_default_context(font_resolver=self._font_resolver, image_store=self._image_store)
        _register_embedded_type1_resources(data, ctx.font_resolver)
        processed_data = preprocess_type1_resources(data)
        dsc = parse_dsc_comments(data)
        ctx.dsc = dsc
        is_eps = _is_eps_document(data)
        if is_eps:
            width, height = page_size_from_dsc(dsc)
        elif dsc is not None and (dsc.crop_box is not None or dsc.document_media_size is not None):
            width, height = page_size_from_dsc(dsc)
        else:
            # For non-EPS jobs, %%BoundingBox often describes content extents,
            # not the page device size. Keep the default A4 page unless an
            # explicit page device/crop size is provided.
            width, height = default_page_size_from_dsc(None)
        ctx.default_page_size = (width, height)
        if is_eps:
            bbox_origin = _bbox_origin_from_dsc(dsc)
            if bbox_origin is not None:
                llx, lly = bbox_origin
                if llx != 0.0 or lly != 0.0:
                    state = ctx.graphics_state_stack.peek()
                    state.ctm = (1.0, 0.0, 0.0, 1.0, -llx, -lly)
        self._builder.set_default_page_size(width, height)
        self._interpreter.execute(processed_data, ctx)
        return self._builder.document()
