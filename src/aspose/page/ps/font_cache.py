"""Font cache for PS/EPS pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import difflib
import shutil
import subprocess
from typing import Iterable

from .errors import PsTypeError


@dataclass(frozen=True)
class FontRecord:
    name: str
    style: str
    path: Path
    is_monospace: bool


@dataclass(frozen=True)
class FontMetrics:
    units_per_em: int
    code_widths: dict[int, float]


class FontCache:
    def __init__(self) -> None:
        self._loaded = False
        self._records: list[FontRecord] = []
        self._metrics_cache: dict[Path, FontMetrics] = {}
        self._additional_folder: Path | None = None

    def load(self, additional_fonts_folder: str | None) -> None:
        if self._loaded:
            return
        if additional_fonts_folder:
            try:
                self._additional_folder = Path(additional_fonts_folder).resolve()
            except OSError:
                self._additional_folder = None
        else:
            self._additional_folder = None
        records: list[FontRecord] = []
        if self._additional_folder is not None and self._additional_folder.exists():
            records.extend(self._scan_folder(self._additional_folder))
        records.extend(self._scan_system_fonts())
        self._records = records
        self._loaded = True

    def find_font(self, font_name: str, font_style: str | None) -> FontRecord | None:
        if not self._loaded:
            self.load(self._additional_folder.as_posix() if self._additional_folder else None)
        name = _normalize_family_name(font_name)
        style = _normalize_style(font_style) if font_style else _infer_style(font_name)
        matches = [rec for rec in self._records if rec.name == name]
        if matches:
            preferred = [rec for rec in matches if rec.style == style]
            if preferred:
                return preferred[0]
            return matches[0]
        return self._nearest_match(name, style)

    def metrics_for(self, path: Path) -> FontMetrics:
        cached = self._metrics_cache.get(path)
        if cached is not None:
            return cached
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise PsTypeError("cannot read font data") from exc
        from .fonts import parse_ttf_metrics
        units, code_widths = parse_ttf_metrics(data)
        metrics = FontMetrics(units, code_widths)
        self._metrics_cache[path] = metrics
        return metrics

    def _nearest_match(self, name: str, style: str) -> FontRecord | None:
        if not self._records:
            return None
        candidates = self._records
        style_matches = [rec for rec in candidates if rec.style == style]
        if style_matches:
            candidates = style_matches
        best = None
        best_ratio = 0.0
        for rec in candidates:
            ratio = difflib.SequenceMatcher(a=name, b=rec.name).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = rec
        # Avoid random substitutions for unrelated families (eg Arial -> Palatino).
        # Callers will fall back to deterministic base-family substitution logic.
        if best is None or best_ratio < 0.86:
            return None
        return best

    def _scan_system_fonts(self) -> list[FontRecord]:
        records: list[FontRecord] = []
        fc_list = shutil.which("fc-list")
        if fc_list:
            try:
                result = subprocess.run(
                    [fc_list, "--format", "%{family}|%{style}|%{file}|%{spacing}\n"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        record = _parse_fc_line(line)
                        if record is not None:
                            records.append(record)
                    return records
            except Exception:
                pass
        for folder in _fallback_system_dirs():
            records.extend(self._scan_folder(folder))
        return records

    def _scan_folder(self, folder: Path) -> list[FontRecord]:
        records: list[FontRecord] = []
        try:
            for path in folder.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in (".ttf", ".otf"):
                    continue
                record = _record_from_path(path)
                if record is not None:
                    records.append(record)
        except OSError:
            return records
        return records


_FONT_CACHE: FontCache | None = None


def get_font_cache() -> FontCache:
    global _FONT_CACHE
    if _FONT_CACHE is None:
        _FONT_CACHE = FontCache()
    return _FONT_CACHE


def _parse_fc_line(line: str) -> FontRecord | None:
    parts = [part.strip() for part in line.split("|")]
    if len(parts) < 4:
        return None
    family = parts[0].split(",")[0]
    style = parts[1].split(",")[0] if parts[1] else ""
    path = Path(parts[2])
    if not path.exists():
        return None
    spacing = parts[3]
    is_monospace = spacing.strip() == "100"
    return FontRecord(
        name=_normalize_family_name(family),
        style=_normalize_style(style or "Regular"),
        path=path,
        is_monospace=is_monospace,
    )


def _record_from_path(path: Path) -> FontRecord | None:
    name = path.stem
    tokens = _split_name_tokens(name)
    style = _infer_style_from_tokens(name, tokens)
    return FontRecord(
        name=_family_from_tokens(name, tokens),
        style=style,
        path=path,
        is_monospace=_name_looks_monospace(name),
    )


def _normalize_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _normalize_family_name(value: str) -> str:
    name = _normalize_name(value)
    return _strip_style_tokens(name)


def _normalize_style(value: str) -> str:
    text = _normalize_name(value)
    if "mediumitalic" in text or "mediumoblique" in text:
        return "Italic"
    if "bold" in text and ("italic" in text or "oblique" in text):
        return "BoldItalic"
    if "bold" in text:
        return "Bold"
    if "italic" in text or "oblique" in text:
        return "Italic"
    return "Regular"


def _infer_style(value: str) -> str:
    return _normalize_style(value)


def _split_name_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^A-Za-z0-9]+", value) if token]


def _infer_style_from_tokens(value: str, tokens: list[str]) -> str:
    text = _normalize_name(value)
    lower_tokens = [token.lower() for token in tokens]
    bold_tokens = {"b", "bd", "bold", "black", "demi"}
    italic_tokens = {"i", "it", "italic", "oblique", "mediumitalic", "mediumoblique"}
    has_bold = any(token in bold_tokens for token in lower_tokens) or "bold" in text
    has_italic = any(token in italic_tokens for token in lower_tokens) or "italic" in text or "oblique" in text
    if has_bold and has_italic:
        return "BoldItalic"
    if has_bold:
        return "Bold"
    if has_italic:
        return "Italic"
    return "Regular"


def _family_from_tokens(value: str, tokens: list[str]) -> str:
    if not tokens:
        return _normalize_family_name(value)
    style_tokens = {
        "mediumitalic",
        "mediumoblique",
        "b",
        "bd",
        "bold",
        "black",
        "demi",
        "i",
        "it",
        "italic",
        "oblique",
        "regular",
        "roman",
        "bolditalic",
        "italicbold",
        "boldoblique",
        "obliquebold",
    }
    family_tokens = [token for token in tokens if token.lower() not in style_tokens]
    if not family_tokens:
        family_tokens = [tokens[0]]
    return _normalize_name("".join(family_tokens))


def _strip_style_tokens(value: str) -> str:
    tokens = [
        "mediumitalic",
        "mediumoblique",
        "bolditalic",
        "italicbold",
        "boldoblique",
        "obliquebold",
        "bold",
        "italic",
        "oblique",
        "regular",
        "roman",
    ]
    result = value
    for token in tokens:
        result = result.replace(token, "")
    return result


def _name_looks_monospace(value: str) -> bool:
    lower = value.lower()
    return "mono" in lower or "fixed" in lower or "courier" in lower


def _fallback_system_dirs() -> Iterable[Path]:
    candidates = [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
    ]
    return [folder for folder in candidates if folder.exists()]
