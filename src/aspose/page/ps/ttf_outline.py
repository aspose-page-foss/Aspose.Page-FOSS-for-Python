"""TrueType glyph outline parsing for raster text rendering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import struct
import time


@dataclass(frozen=True)
class GlyphPoint:
    x: float
    y: float
    on_curve: bool


class TrueTypeFont:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._tables = _parse_table_directory(data)
        head = _require_table(self._tables, b"head")
        maxp = _require_table(self._tables, b"maxp")
        hhea = _require_table(self._tables, b"hhea")
        hmtx = _require_table(self._tables, b"hmtx")
        cmap = _require_table(self._tables, b"cmap")
        loca = _require_table(self._tables, b"loca")
        glyf = _require_table(self._tables, b"glyf")

        self.units_per_em = _read_uint16(data, head + 18)
        self._index_to_loc_format = _read_int16(data, head + 50)
        self._num_glyphs = _read_uint16(data, maxp + 4)
        self._num_hmetrics = _read_uint16(data, hhea + 34)
        self._hhea_ascent = _read_int16(data, hhea + 4)
        self._hhea_descent = _read_int16(data, hhea + 6)
        self._hhea_line_gap = _read_int16(data, hhea + 8)
        self._hmtx_offset = hmtx
        self._loca_offset = loca
        self._glyf_offset = glyf
        self._cmap = _parse_cmap_table(data, cmap)
        os2 = self._tables.get(b"OS/2")
        self._os2_typo_asc: int | None = None
        self._os2_typo_desc: int | None = None
        if os2 is not None and os2 + 78 <= len(data):
            self._os2_typo_asc = _read_int16(data, os2 + 68)
            self._os2_typo_desc = _read_int16(data, os2 + 70)
        vhea = self._tables.get(b"vhea")
        vmtx = self._tables.get(b"vmtx")
        self._vmtx_offset: int | None = vmtx
        self._num_vmetrics: int = (
            _read_uint16(data, vhea + 34) if (vhea is not None and vmtx is not None) else 0
        )

    def glyph_id_for_code(self, code: int) -> int:
        glyph_id = self._cmap.get(code)
        if glyph_id is not None:
            return int(glyph_id)
        # Symbolic cmaps (platform 3, encoding 0) are frequently encoded as
        # U+F0xx private-use values for 8-bit character codes.
        if 0 <= code <= 0xFF:
            glyph_id = self._cmap.get(0xF000 + code)
            if glyph_id is not None:
                return int(glyph_id)
            glyph_id = self._cmap.get(0xF100 + code)
            if glyph_id is not None:
                return int(glyph_id)
        return 0

    def glyph_advance(self, glyph_id: int) -> float:
        glyph_id = max(0, min(glyph_id, self._num_glyphs - 1))
        if glyph_id < self._num_hmetrics:
            offset = self._hmtx_offset + glyph_id * 4
            return float(_read_uint16(self._data, offset))
        last = self._hmtx_offset + (self._num_hmetrics - 1) * 4
        return float(_read_uint16(self._data, last))

    def glyph_vertical_advance(self, glyph_id: int) -> float | None:
        if self._vmtx_offset is None or self._num_vmetrics <= 0:
            return None
        glyph_id = max(0, min(glyph_id, self._num_glyphs - 1))
        if glyph_id < self._num_vmetrics:
            offset = self._vmtx_offset + glyph_id * 4
            return float(_read_uint16(self._data, offset))
        last = self._vmtx_offset + (self._num_vmetrics - 1) * 4
        return float(_read_uint16(self._data, last))

    def line_spacing_units(self) -> float:
        # Prefer hhea line metrics as a stable fallback when vertical metrics
        # are unavailable.
        return float(self._hhea_ascent - self._hhea_descent + self._hhea_line_gap)

    def typo_ascender_units(self) -> float:
        if self._os2_typo_asc is not None:
            return float(self._os2_typo_asc)
        return float(self._hhea_ascent)

    def glyph_top_origin_x(self, glyph_id: int) -> float:
        return self.glyph_advance(glyph_id) * 0.5

    def glyph_top_origin_y_and_descender(self, glyph_id: int) -> tuple[float, float]:
        vm = self.glyph_vertical_metrics(glyph_id)
        y_max = self.glyph_y_max(glyph_id)
        if vm is not None and y_max is not None:
            advance_h, top_side_bearing = vm
            top_origin_y = float(y_max + top_side_bearing)
            descender = max(0.0, float(advance_h - top_origin_y))
            return top_origin_y, descender
        if self._os2_typo_asc is not None and self._os2_typo_desc is not None:
            return float(self._os2_typo_asc), float(abs(self._os2_typo_desc))
        return float(self._hhea_ascent), float(abs(self._hhea_descent))

    def glyph_sideways_advance(self, glyph_id: int) -> float:
        top_origin_y, descender = self.glyph_top_origin_y_and_descender(glyph_id)
        return max(0.0, top_origin_y + descender)

    def glyph_vertical_metrics(self, glyph_id: int) -> tuple[float, float] | None:
        if self._vmtx_offset is None or self._num_vmetrics <= 0:
            return None
        glyph_id = max(0, min(glyph_id, self._num_glyphs - 1))
        if glyph_id < self._num_vmetrics:
            offset = self._vmtx_offset + glyph_id * 4
            advance_h = float(_read_uint16(self._data, offset))
            top_side_bearing = float(_read_int16(self._data, offset + 2))
            return advance_h, top_side_bearing
        adv_off = self._vmtx_offset + (self._num_vmetrics - 1) * 4
        advance_h = float(_read_uint16(self._data, adv_off))
        tsb_off = self._vmtx_offset + self._num_vmetrics * 4 + (glyph_id - self._num_vmetrics) * 2
        if tsb_off + 2 > len(self._data):
            return advance_h, 0.0
        top_side_bearing = float(_read_int16(self._data, tsb_off))
        return advance_h, top_side_bearing

    def glyph_y_max(self, glyph_id: int) -> int | None:
        offsets = self._glyph_offsets()
        if glyph_id >= len(offsets) - 1:
            return None
        start = offsets[glyph_id]
        end = offsets[glyph_id + 1]
        if start == end:
            return None
        header = self._glyf_offset + start
        if header + 10 > self._glyf_offset + end or header + 10 > len(self._data):
            return None
        return int(_read_int16(self._data, header + 8))

    def glyph_outline(self, glyph_id: int) -> list[list[GlyphPoint]]:
        trace_enabled = os.getenv("TTF_TRACE") == "1"
        try:
            max_ms = float(os.getenv("TTF_MAX_MS", "0") or 0.0)
        except ValueError:
            max_ms = 0.0
        try:
            max_components = int(os.getenv("TTF_MAX_COMPONENTS", "0") or 0)
        except ValueError:
            max_components = 0
        deadline = time.perf_counter() + (max_ms / 1000.0) if max_ms > 0 else None
        return self._glyph_outline(glyph_id, set(), deadline, max_components, trace_enabled)

    def _glyph_outline(
        self,
        glyph_id: int,
        visiting: set[int],
        deadline: float | None,
        max_components: int,
        trace_enabled: bool,
    ) -> list[list[GlyphPoint]]:
        offsets = self._glyph_offsets()
        if glyph_id >= len(offsets) - 1:
            return []
        start = offsets[glyph_id]
        end = offsets[glyph_id + 1]
        if start == end:
            return []
        if trace_enabled:
            print(f"TTF TRACE glyph_outline start gid={glyph_id} offset={start} len={end-start}", flush=True)
        contours = _parse_glyph(
            self._data,
            self._glyf_offset + start,
            self._glyf_offset + end,
            self,
            visiting,
            deadline,
            max_components,
            trace_enabled,
        )
        if trace_enabled:
            print(f"TTF TRACE glyph_outline end gid={glyph_id} contours={len(contours)}", flush=True)
        return contours

    def _glyph_offsets(self) -> list[int]:
        if self._index_to_loc_format == 0:
            count = self._num_glyphs + 1
            offsets = [
                _read_uint16(self._data, self._loca_offset + i * 2) * 2
                for i in range(count)
            ]
            return offsets
        count = self._num_glyphs + 1
        return [
            _read_uint32(self._data, self._loca_offset + i * 4)
            for i in range(count)
        ]


def load_ttf_font(path: Path) -> TrueTypeFont:
    return TrueTypeFont(path.read_bytes())


def _parse_glyph(
    data: bytes,
    offset: int,
    glyph_end: int,
    font: TrueTypeFont,
    visiting: set[int],
    deadline: float | None,
    max_components: int,
    trace_enabled: bool,
) -> list[list[GlyphPoint]]:
    if deadline is not None and time.perf_counter() > deadline:
        if trace_enabled:
            print("TTF TRACE timeout before glyph parse", flush=True)
        return []
    if offset + 10 > glyph_end:
        if trace_enabled:
            print("TTF TRACE glyph header out of bounds", flush=True)
        return []
    number_of_contours = _read_int16(data, offset)
    if number_of_contours == 0:
        return []
    if number_of_contours > 0:
        return _parse_simple_glyph(data, offset, glyph_end, number_of_contours, deadline, trace_enabled)
    return _parse_composite_glyph(
        data,
        offset,
        glyph_end,
        font,
        visiting,
        deadline,
        max_components,
        trace_enabled,
    )


def _parse_simple_glyph(
    data: bytes,
    offset: int,
    glyph_end: int,
    contour_count: int,
    deadline: float | None,
    trace_enabled: bool,
) -> list[list[GlyphPoint]]:
    end_pts_offset = offset + 10
    if end_pts_offset + contour_count * 2 + 2 > glyph_end:
        if trace_enabled:
            print("TTF TRACE simple glyph end_pts out of bounds", flush=True)
        return []
    end_pts = [
        _read_uint16(data, end_pts_offset + i * 2) for i in range(contour_count)
    ]
    instruction_length = _read_uint16(data, end_pts_offset + contour_count * 2)
    points_offset = end_pts_offset + contour_count * 2 + 2 + instruction_length
    if points_offset > glyph_end:
        if trace_enabled:
            print("TTF TRACE simple glyph points out of bounds", flush=True)
        return []
    point_count = end_pts[-1] + 1 if end_pts else 0
    remaining_bytes = max(0, glyph_end - points_offset)
    max_points_limit = remaining_bytes * 4
    if max_points_limit == 0:
        return []
    if point_count > max_points_limit:
        if trace_enabled:
            print(
                "TTF TRACE simple glyph point_count clamp {} -> {}".format(
                    point_count, max_points_limit
                ),
                flush=True,
            )
        point_count = max_points_limit

    flags: list[int] = []
    i = 0
    while i < point_count:
        if deadline is not None and time.perf_counter() > deadline:
            if trace_enabled:
                print("TTF TRACE timeout in simple glyph flags", flush=True)
            return []
        if points_offset >= glyph_end:
            if trace_enabled:
                print("TTF TRACE simple glyph flags overrun", flush=True)
            break
        flag = data[points_offset]
        points_offset += 1
        flags.append(flag)
        i += 1
        if flag & 0x08:
            if points_offset >= glyph_end:
                if trace_enabled:
                    print("TTF TRACE simple glyph repeat overrun", flush=True)
                break
            repeat = data[points_offset]
            points_offset += 1
            remaining = point_count - i
            if repeat > remaining:
                if trace_enabled:
                    print("TTF TRACE simple glyph repeat clamp", flush=True)
                repeat = remaining
            if repeat:
                flags.extend([flag] * repeat)
                i += repeat

    if len(flags) > point_count:
        flags = flags[:point_count]

    xs: list[int] = []
    ys: list[int] = []
    x = 0
    for flag in flags:
        if deadline is not None and time.perf_counter() > deadline:
            if trace_enabled:
                print("TTF TRACE timeout in simple glyph x", flush=True)
            return []
        if points_offset >= glyph_end:
            if trace_enabled:
                print("TTF TRACE simple glyph x overrun", flush=True)
            break
        if flag & 0x02:
            dx = data[points_offset]
            points_offset += 1
            if flag & 0x10:
                x += dx
            else:
                x -= dx
        else:
            if flag & 0x10:
                dx = 0
            else:
                if points_offset + 2 > glyph_end:
                    if trace_enabled:
                        print("TTF TRACE simple glyph x short", flush=True)
                    break
                dx = _read_int16(data, points_offset)
                points_offset += 2
            x += dx
        xs.append(x)
    y = 0
    for flag in flags:
        if deadline is not None and time.perf_counter() > deadline:
            if trace_enabled:
                print("TTF TRACE timeout in simple glyph y", flush=True)
            return []
        if points_offset >= glyph_end:
            if trace_enabled:
                print("TTF TRACE simple glyph y overrun", flush=True)
            break
        if flag & 0x04:
            dy = data[points_offset]
            points_offset += 1
            if flag & 0x20:
                y += dy
            else:
                y -= dy
        else:
            if flag & 0x20:
                dy = 0
            else:
                if points_offset + 2 > glyph_end:
                    if trace_enabled:
                        print("TTF TRACE simple glyph y short", flush=True)
                    break
                dy = _read_int16(data, points_offset)
                points_offset += 2
            y += dy
        ys.append(y)

    if not flags or not xs or not ys:
        return []
    max_index = min(len(flags), len(xs), len(ys)) - 1
    if max_index < 0:
        return []
    end_pts = [min(end, max_index) for end in end_pts if end >= 0]
    if not end_pts:
        return []

    contours: list[list[GlyphPoint]] = []
    start = 0
    for end in end_pts:
        if deadline is not None and time.perf_counter() > deadline:
            if trace_enabled:
                print("TTF TRACE timeout in simple glyph contours", flush=True)
            return []
        contour = [
            GlyphPoint(xs[i], ys[i], bool(flags[i] & 0x01))
            for i in range(start, end + 1)
        ]
        contours.append(contour)
        start = end + 1
    return contours


def _parse_composite_glyph(
    data: bytes,
    offset: int,
    glyph_end: int,
    font: TrueTypeFont,
    visiting: set[int],
    deadline: float | None,
    max_components: int,
    trace_enabled: bool,
) -> list[list[GlyphPoint]]:
    contours: list[list[GlyphPoint]] = []
    offset += 10
    flags = 0x20
    component_count = 0
    while flags & 0x20:
        if deadline is not None and time.perf_counter() > deadline:
            if trace_enabled:
                print("TTF TRACE timeout in composite glyph", flush=True)
            return contours
        if offset + 4 > glyph_end:
            if trace_enabled:
                print("TTF TRACE composite glyph overrun", flush=True)
            return contours
        flags = _read_uint16(data, offset)
        glyph_index = _read_uint16(data, offset + 2)
        offset += 4
        if flags & 0x0001:
            if offset + 4 > glyph_end:
                if trace_enabled:
                    print("TTF TRACE composite glyph args overrun", flush=True)
                return contours
            arg1 = _read_int16(data, offset)
            arg2 = _read_int16(data, offset + 2)
            offset += 4
        else:
            if offset + 2 > glyph_end:
                if trace_enabled:
                    print("TTF TRACE composite glyph args short", flush=True)
                return contours
            arg1 = _read_int8(data, offset)
            arg2 = _read_int8(data, offset + 1)
            offset += 2
        dx = arg1 if flags & 0x0002 else 0
        dy = arg2 if flags & 0x0002 else 0

        a = d = 1.0
        b = c = 0.0
        if flags & 0x0008:
            if offset + 2 > glyph_end:
                if trace_enabled:
                    print("TTF TRACE composite glyph scale short", flush=True)
                return contours
            scale = _read_f2dot14(data, offset)
            offset += 2
            a = d = scale
        elif flags & 0x0040:
            if offset + 4 > glyph_end:
                if trace_enabled:
                    print("TTF TRACE composite glyph scale short", flush=True)
                return contours
            a = _read_f2dot14(data, offset)
            d = _read_f2dot14(data, offset + 2)
            offset += 4
        elif flags & 0x0080:
            if offset + 8 > glyph_end:
                if trace_enabled:
                    print("TTF TRACE composite glyph scale short", flush=True)
                return contours
            a = _read_f2dot14(data, offset)
            b = _read_f2dot14(data, offset + 2)
            c = _read_f2dot14(data, offset + 4)
            d = _read_f2dot14(data, offset + 6)
            offset += 8

        if max_components and component_count >= max_components:
            if trace_enabled:
                print("TTF TRACE max components reached", flush=True)
            return contours
        component_count += 1
        if glyph_index in visiting:
            continue
        visiting.add(glyph_index)
        component = font._glyph_outline(glyph_index, visiting, deadline, max_components, trace_enabled)
        visiting.remove(glyph_index)
        for contour in component:
            transformed = [
                GlyphPoint(
                    a * pt.x + c * pt.y + dx,
                    b * pt.x + d * pt.y + dy,
                    pt.on_curve,
                )
                for pt in contour
            ]
            contours.append(transformed)
    return contours


def _parse_table_directory(data: bytes) -> dict[bytes, int]:
    num_tables = _read_uint16(data, 4)
    offset = 12
    tables: dict[bytes, int] = {}
    for _ in range(num_tables):
        tag = data[offset:offset + 4]
        table_offset = _read_uint32(data, offset + 8)
        tables[tag] = table_offset
        offset += 16
    return tables


def _require_table(tables: dict[bytes, int], tag: bytes) -> int:
    if tag not in tables:
        raise ValueError(f"missing {tag!r} table")
    return tables[tag]


def _parse_cmap_table(data: bytes, offset: int) -> dict[int, int]:
    version = _read_uint16(data, offset)
    if version != 0:
        return {}
    num_tables = _read_uint16(data, offset + 2)
    chosen_offset = None
    symbol_offset = None
    unicode_bmp_offset = None
    unicode_full_offset = None
    platform0_offset = None
    for i in range(num_tables):
        record_offset = offset + 4 + i * 8
        platform_id = _read_uint16(data, record_offset)
        encoding_id = _read_uint16(data, record_offset + 2)
        sub_offset = _read_uint32(data, record_offset + 4)
        candidate = offset + sub_offset
        if platform_id == 3 and encoding_id == 10:
            unicode_full_offset = candidate
        elif platform_id == 3 and encoding_id == 1:
            unicode_bmp_offset = candidate
        elif platform_id == 3 and encoding_id == 0:
            symbol_offset = candidate
        elif platform_id == 0 and platform0_offset is None:
            platform0_offset = candidate
    chosen_offset = (
        unicode_full_offset
        or unicode_bmp_offset
        or symbol_offset
        or platform0_offset
    )
    if chosen_offset is None:
        return {}
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
    num_groups = _read_uint32(data, offset + 12)
    cmap: dict[int, int] = {}
    group_offset = offset + 16
    for i in range(num_groups):
        start_char = _read_uint32(data, group_offset + i * 12)
        end_char = _read_uint32(data, group_offset + i * 12 + 4)
        start_glyph = _read_uint32(data, group_offset + i * 12 + 8)
        for code in range(start_char, end_char + 1):
            cmap[int(code)] = int(start_glyph + (code - start_char))
    return cmap


def _read_uint16(data: bytes, offset: int) -> int:
    return struct.unpack(">H", data[offset:offset + 2])[0]


def _read_int16(data: bytes, offset: int) -> int:
    return struct.unpack(">h", data[offset:offset + 2])[0]


def _read_uint32(data: bytes, offset: int) -> int:
    return struct.unpack(">I", data[offset:offset + 4])[0]


def _read_int8(data: bytes, offset: int) -> int:
    return struct.unpack(">b", data[offset:offset + 1])[0]


def _read_f2dot14(data: bytes, offset: int) -> float:
    value = _read_int16(data, offset)
    return float(value) / 16384.0
