"""Font resolution utilities for PS/EPS."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from pathlib import Path
import subprocess

from .encodings import (
    ISO_LATIN1_ENCODING,
    STANDARD_ENCODING,
    SYMBOL_ENCODING,
    ZAPF_DINGBATS_ENCODING,
)
from .errors import PsTypeError, PsUndefinedError
from .font_cache import FontCache, get_font_cache
from .objects import PsArray, PsDict, PsName, PsProcedure


@dataclass(frozen=True)
class FontResource:
    """Represents a resolved font resource.

    Example:
        >>> resource = FontResource("Helvetica", "Type1", 1000, {}, {}, False)
        >>> resource.name
        'Helvetica'
    """

    name: str
    font_type: str
    units_per_em: int
    encoding: dict[int, str]
    glyph_widths: dict[str, float]
    substitute: bool
    char_procs: dict[str, PsProcedure] | None = None
    code_widths: dict[int, float] | None = None
    descendant: "FontResource | None" = None
    esc_char: int | None = None
    fdep_vector: list["FontResource"] | None = None
    fmap_encoding: list[int] | None = None
    font_dict: PsDict | None = None
    code_map: dict[int, int] | None = None
    font_program: bytes | None = None
    fmap_type: int | None = None


@dataclass(frozen=True)
class EmbeddedType42:
    data: bytes
    units_per_em: int
    code_widths: dict[int, float]


class FontResolver:
    """Resolve fonts from names or PostScript dictionaries.

    Example:
        >>> resolver = FontResolver()
        >>> resolver.resolve("MissingFont").substitute
        True
    """

    def __init__(
        self,
        additional_fonts_folder: str | None = None,
        font_cache: FontCache | None = None,
    ) -> None:
        self._resource_root = Path(__file__).resolve().parents[4] / "resources"
        self._additional_fonts_folder = (
            Path(additional_fonts_folder).resolve() if additional_fonts_folder else None
        )
        self._font_cache = font_cache or get_font_cache()
        self._font_cache.load(additional_fonts_folder)
        self._aliases: dict[str, str] = {
            # Common PostScript names emitted by Office/Cairo workflows.
            "ArialMT": "Helvetica",
            "Arial-BoldMT": "Helvetica-Bold",
            "Arial-ItalicMT": "Helvetica-Oblique",
            "Arial-BoldItalicMT": "Helvetica-BoldOblique",
            "TimesNewRomanPSMT": "Times-Roman",
            "TimesNewRomanPS-BoldMT": "Times-Bold",
            "TimesNewRomanPS-ItalicMT": "Times-Italic",
            "TimesNewRomanPS-BoldItalicMT": "Times-BoldItalic",
            "TimesNewRomanPS-BoldMT": "Times-Bold",
            "SymbolMT": "Symbol",
            "ZapfDingbatsITC": "ZapfDingbats",
        }
        self._embedded_type42: dict[str, EmbeddedType42] = {}
        self._defined_fonts: dict[str, FontResource] = {}

    def _apply_alias(self, font_name: str) -> str:
        return self._aliases.get(font_name, font_name)

    def resolve(self, font_name: str) -> FontResource:
        defined = self._defined_fonts.get(font_name)
        if defined is not None:
            return defined
        font_name = self._apply_alias(font_name)
        defined = self._defined_fonts.get(font_name)
        if defined is not None:
            return defined
        embedded = self._embedded_type42.get(font_name)
        if embedded is not None:
            glyph_widths = _glyph_widths_from_encoding(embedded.code_widths, STANDARD_ENCODING)
            return FontResource(
                font_name,
                "Type42",
                embedded.units_per_em,
                STANDARD_ENCODING,
                glyph_widths,
                False,
                code_widths=embedded.code_widths,
                font_program=embedded.data,
            )
        if font_name in ("ZapfDingbats", "Wingdings", "Webdings"):
            return self._fallback_dingbats(font_name)
        if font_name in ("Symbol",):
            return self._fallback_symbol(font_name)
        if font_name in (
            "Helvetica",
            "Helvetica-Bold",
            "Helvetica-Oblique",
            "Helvetica-BoldOblique",
            "Times-Roman",
            "Times-Bold",
            "Times-Italic",
            "Times-BoldItalic",
            "Courier",
            "Courier-Bold",
            "Courier-Oblique",
            "Courier-BoldOblique",
        ):
            code_widths = None
            glyph_widths: dict[str, float] = {}
            units = 1000
            ttf_path = self.resolve_ttf_path(font_name)
            if ttf_path is not None and ttf_path.exists():
                units, code_widths = self._load_ttf_metrics(ttf_path)
                glyph_widths = _glyph_widths_from_encoding(code_widths, STANDARD_ENCODING)
            elif font_name.startswith("Courier"):
                code_widths = {code: 600.0 for code in range(256)}
                glyph_widths = _glyph_widths_from_encoding(code_widths, STANDARD_ENCODING)
            return FontResource(
                font_name,
                "Type1",
                units,
                STANDARD_ENCODING,
                glyph_widths,
                False,
                code_widths=code_widths,
            )
        record = self._font_cache.find_font(font_name, None)
        if record is not None:
            try:
                units, code_widths = self._load_ttf_metrics(record.path)
                glyph_widths = _glyph_widths_from_encoding(code_widths, STANDARD_ENCODING)
                return FontResource(
                    font_name,
                    "Type42",
                    units,
                    STANDARD_ENCODING,
                    glyph_widths,
                    True,
                    code_widths=code_widths,
                )
            except Exception:
                return self._fallback_liberation(font_name)
        return self._fallback_liberation(font_name)

    def resolve_ttf_path(self, font_name: str) -> Path | None:
        """Resolve a TrueType/OpenType path for a font name when available."""
        font_name = self._apply_alias(font_name)
        if font_name in self._defined_fonts:
            defined = self._defined_fonts.get(font_name)
            if defined is not None and defined.font_program:
                return None
            base_alias = self._aliases.get(font_name)
            if base_alias and base_alias != font_name:
                return self.resolve_ttf_path(base_alias)
            # Common convention for re-encoded variants:
            #   Palatino-Roman-Reverse -> Palatino-Roman
            if "-" in font_name:
                base = font_name.rsplit("-", 1)[0]
                if base and base != font_name:
                    return self.resolve_ttf_path(base)
            return None
        if font_name in self._embedded_type42:
            return None
        if font_name in ("ZapfDingbats",):
            path = self._resolve_zapf_path()
            return path if path is not None and path.exists() else None
        if font_name in ("Wingdings", "Webdings"):
            path = self._resource_root / "djVuDingbats.ttf"
            return path if path.exists() else None
        if font_name == "Symbol":
            path = self._resolve_symbol_path()
            return path if path is not None and path.exists() else None
        record = self._font_cache.find_font(font_name, None)
        if record is not None and record.path.exists():
            return record.path
        fallback = self._resolve_liberation_path(font_name)
        return fallback if fallback.exists() else None

    def _encoding_from_dict(self, font_dict: PsDict) -> dict[int, str]:
        encoding_value = font_dict.items.get("Encoding")
        if isinstance(encoding_value, str):
            if encoding_value == "SymbolEncoding":
                return SYMBOL_ENCODING
            if encoding_value == "ZapfDingbatsEncoding":
                return ZAPF_DINGBATS_ENCODING
            if encoding_value in ("ISOLatin1Encoding", "ISOLatin1"):
                return ISO_LATIN1_ENCODING
            return STANDARD_ENCODING
        if isinstance(encoding_value, PsName):
            name = encoding_value.value
            if name == "SymbolEncoding":
                return SYMBOL_ENCODING
            if name == "ZapfDingbatsEncoding":
                return ZAPF_DINGBATS_ENCODING
            if name in ("ISOLatin1Encoding", "ISOLatin1"):
                return ISO_LATIN1_ENCODING
            return STANDARD_ENCODING
        if isinstance(encoding_value, PsArray):
            mapping: dict[int, str] = {}
            for index, item in enumerate(encoding_value.items):
                if isinstance(item, PsName):
                    mapping[index] = item.value
                elif isinstance(item, str):
                    mapping[index] = item
            if mapping:
                return mapping
        if isinstance(encoding_value, PsDict):
            base_value = encoding_value.items.get("BaseEncoding")
            if isinstance(base_value, PsName):
                if base_value.value == "SymbolEncoding":
                    base = dict(SYMBOL_ENCODING)
                elif base_value.value == "ZapfDingbatsEncoding":
                    base = dict(ZAPF_DINGBATS_ENCODING)
                elif base_value.value in ("ISOLatin1Encoding", "ISOLatin1"):
                    base = dict(ISO_LATIN1_ENCODING)
                else:
                    base = dict(STANDARD_ENCODING)
            else:
                base = dict(STANDARD_ENCODING)
            differences = encoding_value.items.get("Differences")
            if isinstance(differences, PsArray):
                code = None
                for item in differences.items:
                    if isinstance(item, (int, float)):
                        code = int(item)
                        continue
                    if code is None:
                        continue
                    if isinstance(item, PsName):
                        base[code] = item.value
                        code += 1
                    elif isinstance(item, str):
                        base[code] = item
                        code += 1
            return base
        return STANDARD_ENCODING

    def resolve_from_dict(self, font_dict: PsDict) -> FontResource:
        font_type_value = font_dict.items.get("FontType")
        font_type = _normalize_font_type(font_type_value)
        font_name_value = font_dict.items.get("FontName")
        if isinstance(font_name_value, PsName):
            font_name = font_name_value.value
        elif isinstance(font_name_value, str):
            font_name = font_name_value
        else:
            font_name = "UnknownFont"

        encoding = self._encoding_from_dict(font_dict)
        if font_type in ("Type1", "Type3", "Type42"):
            from .font_types import load_type1_font, load_type3_font, load_type42_font

            if font_type == "Type1":
                resource = load_type1_font(font_dict)
            elif font_type == "Type3":
                resource = load_type3_font(font_dict)
            else:
                try:
                    resource = load_type42_font(font_dict)
                except PsTypeError:
                    # Some procsets clone/findfont Type42 dictionaries and rely
                    # on inherited resolver data rather than an explicit sfnts
                    # payload in the cloned dictionary.
                    resource = self.resolve(font_name)
                if resource.font_program is not None and resource.code_widths is not None:
                    self.register_embedded_type42(
                        font_name,
                        resource.font_program,
                        resource.units_per_em,
                        resource.code_widths,
                    )
            glyph_widths = resource.glyph_widths
            if resource.code_widths is not None:
                glyph_widths = _glyph_widths_from_encoding(resource.code_widths, encoding)
            return FontResource(
                name=font_name,
                font_type=resource.font_type,
                units_per_em=resource.units_per_em,
                encoding=encoding,
                glyph_widths=glyph_widths,
                substitute=False,
                char_procs=resource.char_procs,
                code_widths=resource.code_widths,
                font_dict=font_dict,
                font_program=resource.font_program,
                code_map=resource.code_map,
            )
        if font_type in ("Type0", "CIDKeyed"):
            descendants: list[FontResource] = []
            descendant_value = font_dict.items.get("DescendantFonts")
            if isinstance(descendant_value, PsArray):
                for item in descendant_value.items:
                    if isinstance(item, PsDict):
                        descendants.append(self.resolve_from_dict(item))
                    elif isinstance(item, FontResource):
                        descendants.append(item)

            fdep_value = font_dict.items.get("FDepVector")
            if isinstance(fdep_value, PsArray):
                index = 0
                items = fdep_value.items
                while index < len(items):
                    item = items[index]
                    next_item = items[index + 1] if index + 1 < len(items) else None
                    # Common PostScript pattern: [/FontName findfont ...]
                    if (
                        isinstance(item, PsName)
                        and isinstance(next_item, PsName)
                        and next_item.value == "findfont"
                    ):
                        descendants.append(self.resolve(item.value))
                        index += 2
                        continue
                    if (
                        isinstance(item, str)
                        and isinstance(next_item, PsName)
                        and next_item.value == "findfont"
                    ):
                        descendants.append(self.resolve(item))
                        index += 2
                        continue
                    if isinstance(item, FontResource):
                        descendants.append(item)
                    elif isinstance(item, PsDict):
                        descendants.append(self.resolve_from_dict(item))
                    elif isinstance(item, PsName):
                        descendants.append(self.resolve(item.value))
                    elif isinstance(item, str):
                        descendants.append(self.resolve(item))
                    index += 1

            descendant = descendants[0] if descendants else None
            esc_char = None
            esc_value = font_dict.items.get("EscChar")
            if isinstance(esc_value, (int, float)):
                esc_char = int(esc_value) & 0xFF

            fmap_encoding = None
            encoding_value = font_dict.items.get("Encoding")
            if isinstance(encoding_value, PsArray):
                mapped: list[int] = []
                for item in encoding_value.items:
                    if isinstance(item, (int, float)):
                        mapped.append(int(item))
                if mapped:
                    fmap_encoding = mapped
            fmap_type = None
            fmap_value = font_dict.items.get("FMapType")
            if isinstance(fmap_value, (int, float)):
                fmap_type = int(fmap_value)

            resolved_encoding = descendant.encoding if descendant is not None else encoding
            code_map = None
            raw_map = font_dict.items.get("__CodeMap__")
            if isinstance(raw_map, dict):
                parsed: dict[int, int] = {}
                for key, value in raw_map.items():
                    if isinstance(key, int) and isinstance(value, int):
                        parsed[int(key)] = int(value)
                if parsed:
                    code_map = parsed
            return FontResource(
                name=font_name,
                font_type=font_type,
                units_per_em=1000,
                encoding=resolved_encoding,
                glyph_widths=descendant.glyph_widths if descendant else {},
                substitute=False,
                descendant=descendant,
                code_widths=descendant.code_widths if descendant else None,
                esc_char=esc_char,
                fdep_vector=descendants or None,
                fmap_encoding=fmap_encoding,
                font_dict=font_dict,
                code_map=code_map,
                fmap_type=fmap_type,
            )
        raise PsUndefinedError(f"unsupported font type {font_type}")

    def register_embedded_type42(
        self,
        font_name: str,
        data: bytes,
        units_per_em: int,
        code_widths: dict[int, float],
    ) -> None:
        self._embedded_type42[font_name] = EmbeddedType42(
            data=data,
            units_per_em=units_per_em,
            code_widths=dict(code_widths),
        )

    def get_embedded_type42(self, font_name: str) -> EmbeddedType42 | None:
        return self._embedded_type42.get(self._apply_alias(font_name))

    def register_defined_font(self, font_name: str, resource: FontResource) -> None:
        self._defined_fonts[font_name] = resource

    def get_glyph_width(self, font: FontResource, glyph_name: str) -> float:
        if glyph_name in font.glyph_widths:
            return font.glyph_widths[glyph_name]
        if ".notdef" in font.glyph_widths:
            return font.glyph_widths[".notdef"]
        return 0.0

    def _fallback_liberation(self, font_name: str) -> FontResource:
        path = self._resolve_liberation_path(font_name)
        if path is None or not path.exists():
            return FontResource(font_name, "Type1", 1000, STANDARD_ENCODING, {}, True)
        units, code_widths = self._load_ttf_metrics(path)
        glyph_widths = _glyph_widths_from_encoding(code_widths, STANDARD_ENCODING)
        return FontResource(
            font_name,
            "Type42",
            units,
            STANDARD_ENCODING,
            glyph_widths,
            True,
            code_widths=code_widths,
        )

    def _fallback_dingbats(self, font_name: str) -> FontResource:
        path = self._resolve_zapf_path()
        if path is None or not path.exists():
            return FontResource(font_name, "Type1", 1000, ZAPF_DINGBATS_ENCODING, {}, True)
        units, code_widths = self._load_ttf_metrics(path)
        glyph_widths = _glyph_widths_from_encoding(code_widths, ZAPF_DINGBATS_ENCODING)
        return FontResource(
            font_name,
            "Type42",
            units,
            ZAPF_DINGBATS_ENCODING,
            glyph_widths,
            True,
            code_widths=code_widths,
        )

    def _fallback_symbol(self, font_name: str) -> FontResource:
        path = self._resolve_symbol_path()
        if path is None or not path.exists():
            return FontResource(font_name, "Type1", 1000, SYMBOL_ENCODING, {}, True)
        units, code_widths = self._load_ttf_metrics(path)
        glyph_widths = _glyph_widths_from_encoding(code_widths, SYMBOL_ENCODING)
        return FontResource(
            font_name,
            "Type42",
            units,
            SYMBOL_ENCODING,
            glyph_widths,
            True,
            code_widths=code_widths,
        )

    def _resolve_symbol_path(self) -> Path | None:
        found = _system_font(
            [
                "Standard Symbols PS:style=Regular",
                "Standard Symbols PS",
                "Symbol",
            ]
        )
        if found is not None:
            return found
        return None

    def _resolve_zapf_path(self) -> Path | None:
        local_candidates = (
            self._additional_fonts_folder / "ITCZapfDingbats.ttf"
            if self._additional_fonts_folder
            else None,
            self._additional_fonts_folder / "ZapfDingbats.ttf"
            if self._additional_fonts_folder
            else None,
            self._resource_root / "djVuDingbats.ttf",
        )
        for candidate in local_candidates:
            if candidate is not None and candidate.exists():
                return candidate
        found = _system_font(
            [
                "ITC Zapf Dingbats:style=Regular",
                "Zapf Dingbats",
                "Dingbats",
                "D050000L",
            ]
        )
        if found is not None:
            return found
        return None

    def _resolve_liberation_path(self, font_name: str) -> Path | None:
        name = font_name.lower()
        if name.startswith("arial"):
            windows_arial = self._resolve_windows_arial_path(name)
            if windows_arial is not None:
                return windows_arial
            if "bold" in name and ("italic" in name or "oblique" in name):
                found = _system_font(
                    [
                        "Arimo:style=Bold Italic",
                        "Arimo Bold Italic",
                        "Arial:style=Bold Italic",
                        "Arial Bold Italic",
                        "Nimbus Sans:style=Bold Italic",
                        "Nimbus Sans Bold Italic",
                        "Liberation Sans Bold Italic",
                        "DejaVu Sans Bold Oblique",
                    ]
                )
                if found is not None:
                    return found
            if "bold" in name:
                found = _system_font(
                    [
                        "Arimo:style=Bold",
                        "Arimo Bold",
                        "Arial:style=Bold",
                        "Arial Bold",
                        "Nimbus Sans:style=Bold",
                        "Nimbus Sans Bold",
                        "Liberation Sans Bold",
                        "DejaVu Sans Bold",
                    ]
                )
                if found is not None:
                    return found
            if "italic" in name or "oblique" in name:
                found = _system_font(
                    [
                        "Arimo:style=Italic",
                        "Arimo Italic",
                        "Arial:style=Italic",
                        "Arial Italic",
                        "Nimbus Sans:style=Italic",
                        "Nimbus Sans Italic",
                        "Liberation Sans Italic",
                        "DejaVu Sans Oblique",
                    ]
                )
                if found is not None:
                    return found
            found = _system_font(
                [
                    "Arimo:style=Regular",
                    "Arimo",
                    "Arimo Regular",
                    "Arimo-R",
                    "Nimbus Sans:style=Regular",
                    "Nimbus Sans",
                    "Arial:style=Regular",
                    "Arial",
                    "Liberation Sans Regular",
                    "DejaVu Sans",
                ]
            )
            if found is not None:
                return found
        if name.startswith("courier"):
            if "bold" in name and ("italic" in name or "oblique" in name):
                found = _system_font(
                    [
                        "Nimbus Mono PS:style=Bold Italic",
                        "Nimbus Mono PS Bold Italic",
                        "NimbusMonoPS-BoldItalic",
                        "Liberation Mono Bold Italic",
                        "DejaVu Sans Mono Bold Oblique",
                    ]
                )
                if found is not None:
                    return found
            if "bold" in name:
                found = _system_font(
                    [
                        "Nimbus Mono PS:style=Bold",
                        "Nimbus Mono PS Bold",
                        "NimbusMonoPS-Bold",
                        "Liberation Mono Bold",
                        "DejaVu Sans Mono Bold",
                    ]
                )
                if found is not None:
                    return found
            if "italic" in name or "oblique" in name:
                found = _system_font(
                    [
                        "Nimbus Mono PS:style=Italic",
                        "Nimbus Mono PS Italic",
                        "NimbusMonoPS-Italic",
                        "Liberation Mono Italic",
                        "DejaVu Sans Mono Oblique",
                    ]
                )
                if found is not None:
                    return found
            found = _system_font(
                [
                    "Nimbus Mono PS:style=Regular",
                    "Nimbus Mono PS",
                    "NimbusMonoPS-Regular",
                    "Liberation Mono Regular",
                    "DejaVu Sans Mono Book",
                    "DejaVu Sans Mono",
                ]
            )
            if found is not None:
                return found
        if name.startswith("helvetica"):
            if "bold" in name and ("italic" in name or "oblique" in name):
                found = _system_font(
                    [
                        "Nimbus Sans:style=Bold Italic",
                        "Nimbus Sans Bold Italic",
                        "NimbusSans-BoldItalic",
                        "Liberation Sans Bold Italic",
                        "DejaVu Sans Bold Oblique",
                    ]
                )
                if found is not None:
                    return found
            if "bold" in name:
                found = _system_font(
                    [
                        "Nimbus Sans:style=Bold",
                        "Nimbus Sans Bold",
                        "NimbusSans-Bold",
                        "Liberation Sans Bold",
                        "DejaVu Sans Bold",
                    ]
                )
                if found is not None:
                    return found
            if "italic" in name or "oblique" in name:
                found = _system_font(
                    [
                        "Nimbus Sans:style=Italic",
                        "Nimbus Sans Italic",
                        "NimbusSans-Italic",
                        "Liberation Sans Italic",
                        "DejaVu Sans Oblique",
                    ]
                )
                if found is not None:
                    return found
            found = _system_font(
                [
                    "Nimbus Sans:style=Regular",
                    "Nimbus Sans",
                    "NimbusSans-Regular",
                    "Liberation Sans Regular",
                    "DejaVu Sans",
                ]
            )
            if found is not None:
                return found
        if name.startswith("times"):
            if "bold" in name and ("italic" in name or "oblique" in name):
                found = _system_font(
                    [
                        "Nimbus Roman:style=Bold Italic",
                        "Nimbus Roman Bold Italic",
                        "NimbusRoman-BoldItalic",
                        "Liberation Serif Bold Italic",
                        "DejaVu Serif Bold Italic",
                    ]
                )
                if found is not None:
                    return found
            if "bold" in name:
                found = _system_font(
                    [
                        "Nimbus Roman:style=Bold",
                        "Nimbus Roman Bold",
                        "NimbusRoman-Bold",
                        "Liberation Serif Bold",
                        "DejaVu Serif Bold",
                    ]
                )
                if found is not None:
                    return found
            if "italic" in name or "oblique" in name:
                found = _system_font(
                    [
                        "Nimbus Roman:style=Italic",
                        "Nimbus Roman Italic",
                        "NimbusRoman-Italic",
                        "Liberation Serif Italic",
                        "DejaVu Serif Italic",
                    ]
                )
                if found is not None:
                    return found
            found = _system_font(
                [
                    "Nimbus Roman:style=Regular",
                    "Nimbus Roman",
                    "NimbusRoman-Regular",
                    "Liberation Serif Regular",
                    "DejaVu Serif",
                ]
            )
            if found is not None:
                return found
        if "bold" in name and ("italic" in name or "oblique" in name):
            return self._resource_root / "LiberationSerif-BoldItalic.ttf"
        if "bold" in name:
            return self._resource_root / "LiberationSerif-Bold.ttf"
        if "italic" in name or "oblique" in name:
            return self._resource_root / "LiberationSerif-Italic.ttf"
        return self._resource_root / "LiberationSerif-Regular.ttf"

    def _resolve_windows_arial_path(self, lower_name: str) -> Path | None:
        windows_fonts = Path("/mnt/c/Windows/Fonts")
        if not windows_fonts.exists():
            return None
        if "bold" in lower_name and ("italic" in lower_name or "oblique" in lower_name):
            candidate = windows_fonts / "arialbi.ttf"
        elif "bold" in lower_name:
            candidate = windows_fonts / "arialbd.ttf"
        elif "italic" in lower_name or "oblique" in lower_name:
            candidate = windows_fonts / "ariali.ttf"
        else:
            candidate = windows_fonts / "arial.ttf"
        if candidate.exists():
            return candidate
        return None

    def _load_ttf_metrics(self, path: Path) -> tuple[int, dict[int, float]]:
        metrics = self._font_cache.metrics_for(path)
        return metrics.units_per_em, metrics.code_widths


def _system_font(families: list[str]) -> Path | None:
    try:
        for family in families:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", family],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                candidate = result.stdout.strip()
                if candidate:
                    path = Path(candidate)
                    if path.exists():
                        return path
    except Exception:
        pass
    return None


def _normalize_font_type(value: object) -> str:
    if isinstance(value, PsName):
        value = value.value
    if isinstance(value, (int, float)):
        if int(value) == 0:
            return "Type0"
        if int(value) == 1:
            return "Type1"
        if int(value) == 3:
            return "Type3"
        if int(value) == 42:
            return "Type42"
    if isinstance(value, str):
        normalized = value.lstrip("/")
        if normalized in ("Type0", "CIDKeyed", "Type1", "Type3", "Type42"):
            return normalized
        if normalized.isdigit():
            return _normalize_font_type(int(normalized))
    raise PsTypeError("unsupported font type")


def _normalize_font_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _glyph_widths_from_encoding(
    code_widths: dict[int, float], encoding: dict[int, str]
) -> dict[str, float]:
    widths: dict[str, float] = {}
    for code, name in encoding.items():
        width = code_widths.get(code)
        if width is None:
            continue
        widths[name] = width
    return widths


def parse_ttf_metrics(data: bytes) -> tuple[int, dict[int, float]]:
    tables = _parse_table_directory(data)
    head = tables.get(b"head")
    hhea = tables.get(b"hhea")
    maxp = tables.get(b"maxp")
    hmtx = tables.get(b"hmtx")
    cmap = tables.get(b"cmap")
    if head is None or hhea is None or maxp is None or hmtx is None or cmap is None:
        raise PsTypeError("missing TrueType tables")
    units_per_em = _read_uint16(data, head + 18)
    num_hmetrics = _read_uint16(data, hhea + 34)
    num_glyphs = _read_uint16(data, maxp + 4)
    widths = _read_hmtx_widths(data, hmtx, num_hmetrics, num_glyphs)
    cmap_map = _parse_cmap_table(data, cmap)
    code_widths: dict[int, float] = {}
    for code, glyph_id in cmap_map.items():
        if glyph_id < len(widths):
            code_widths[code] = widths[glyph_id]
    return units_per_em, code_widths


def _parse_table_directory(data: bytes) -> dict[bytes, int]:
    if len(data) < 12:
        raise PsTypeError("invalid TrueType data")
    num_tables = _read_uint16(data, 4)
    offset = 12
    tables: dict[bytes, int] = {}
    for _ in range(num_tables):
        tag = data[offset:offset + 4]
        table_offset = struct.unpack(">I", data[offset + 8:offset + 12])[0]
        tables[tag] = table_offset
        offset += 16
    return tables


def _read_hmtx_widths(
    data: bytes, offset: int, num_hmetrics: int, num_glyphs: int
) -> list[float]:
    widths: list[float] = []
    current = offset
    last_width = 0
    for _ in range(num_hmetrics):
        width = _read_uint16(data, current)
        last_width = width
        widths.append(float(width))
        current += 4
    while len(widths) < num_glyphs:
        widths.append(float(last_width))
    return widths


def _parse_cmap_table(data: bytes, offset: int) -> dict[int, int]:
    version = _read_uint16(data, offset)
    if version != 0:
        raise PsTypeError("unsupported cmap version")
    num_tables = _read_uint16(data, offset + 2)
    candidates: list[tuple[int, int]] = []
    for i in range(num_tables):
        record_offset = offset + 4 + i * 8
        platform_id = _read_uint16(data, record_offset)
        encoding_id = _read_uint16(data, record_offset + 2)
        sub_offset = struct.unpack(">I", data[record_offset + 4:record_offset + 8])[0]
        if platform_id == 3 and encoding_id == 10:
            candidates.append((0, offset + sub_offset))
        elif platform_id == 3 and encoding_id == 1:
            candidates.append((1, offset + sub_offset))
        elif platform_id == 0:
            candidates.append((2, offset + sub_offset))
        elif platform_id == 3 and encoding_id == 0:
            # Symbol cmap (eg Webdings, Wingdings); often exposes U+F0xx mappings.
            candidates.append((3, offset + sub_offset))
    for _, chosen_offset in sorted(candidates, key=lambda item: item[0]):
        fmt = _read_uint16(data, chosen_offset)
        if fmt == 4:
            return _parse_cmap_format4(data, chosen_offset)
        if fmt == 12:
            return _parse_cmap_format12(data, chosen_offset)
    return {}


def _parse_cmap_format4(data: bytes, offset: int) -> dict[int, int]:
    seg_count = _read_uint16(data, offset + 6) // 2
    end_offset = offset + 14
    end_codes = [ _read_uint16(data, end_offset + i * 2) for i in range(seg_count) ]
    start_offset = end_offset + seg_count * 2 + 2
    start_codes = [ _read_uint16(data, start_offset + i * 2) for i in range(seg_count) ]
    delta_offset = start_offset + seg_count * 2
    deltas = [ _read_int16(data, delta_offset + i * 2) for i in range(seg_count) ]
    range_offset = delta_offset + seg_count * 2
    range_offsets = [ _read_uint16(data, range_offset + i * 2) for i in range(seg_count) ]
    glyph_array_offset = range_offset + seg_count * 2

    cmap: dict[int, int] = {}
    for i in range(seg_count):
        start = start_codes[i]
        end = end_codes[i]
        if start > end:
            continue
        for code in range(start, end + 1):
            if code == 0xFFFF:
                continue
            roffset = range_offsets[i]
            if roffset == 0:
                glyph_id = (code + deltas[i]) & 0xFFFF
            else:
                idx = (roffset // 2) + (code - start) - (seg_count - i)
                glyph_offset = glyph_array_offset + idx * 2
                if glyph_offset + 2 > len(data):
                    continue
                glyph_id = _read_uint16(data, glyph_offset)
                if glyph_id != 0:
                    glyph_id = (glyph_id + deltas[i]) & 0xFFFF
            cmap[code] = glyph_id
    return cmap


def _parse_cmap_format12(data: bytes, offset: int) -> dict[int, int]:
    num_groups = struct.unpack(">I", data[offset + 12:offset + 16])[0]
    cmap: dict[int, int] = {}
    group_offset = offset + 16
    for i in range(num_groups):
        start_char, end_char, start_glyph = struct.unpack(
            ">III", data[group_offset + i * 12:group_offset + (i + 1) * 12]
        )
        for code in range(start_char, end_char + 1):
            cmap[int(code)] = int(start_glyph + (code - start_char))
    return cmap


def _read_uint16(data: bytes, offset: int) -> int:
    return struct.unpack(">H", data[offset:offset + 2])[0]


def _read_int16(data: bytes, offset: int) -> int:
    return struct.unpack(">h", data[offset:offset + 2])[0]
