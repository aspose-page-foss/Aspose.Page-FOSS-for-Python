"""TrueType subsetting for PDF embedding."""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Iterable

from .errors import PsTypeError


@dataclass(frozen=True)
class _TableRecord:
    tag: bytes
    checksum: int
    offset: int
    length: int


def subset_ttf(
    data: bytes,
    used_codes: set[int],
    code_remap: dict[int, int] | None = None,
) -> tuple[bytes, dict[int, int]]:
    if not data:
        raise PsTypeError("empty TrueType data")
    records = _read_table_directory(data)
    table_map = {rec.tag: rec for rec in records}
    required = [b"head", b"hhea", b"maxp", b"hmtx", b"loca", b"glyf", b"cmap"]
    for tag in required:
        if tag not in table_map:
            raise PsTypeError("missing TrueType tables")

    head = table_map[b"head"]
    hhea = table_map[b"hhea"]
    maxp = table_map[b"maxp"]
    hmtx = table_map[b"hmtx"]
    loca = table_map[b"loca"]
    glyf = table_map[b"glyf"]
    cmap = table_map[b"cmap"]

    head_data = bytearray(_slice_table(data, head))
    hhea_data = bytearray(_slice_table(data, hhea))
    maxp_data = bytearray(_slice_table(data, maxp))

    if len(head_data) < 54 or len(hhea_data) < 36 or len(maxp_data) < 6:
        raise PsTypeError("invalid TrueType tables")

    index_to_loc_format = _read_int16(head_data, 50)
    num_glyphs = _read_uint16(maxp_data, 4)
    num_hmetrics = _read_uint16(hhea_data, 34)

    offsets = _read_loca(data, loca.offset, index_to_loc_format, num_glyphs)
    cmap_map = _parse_cmap_table(data, cmap.offset)

    if code_remap:
        codes = sorted(code for code in code_remap.keys() if 0 <= code <= 0xFFFF)
        code_to_gid = {}
        for code in codes:
            src = int(code_remap.get(code, code))
            code_to_gid[code] = int(cmap_map.get(src, 0))
    else:
        codes = sorted(code for code in used_codes if 0 <= code <= 0xFFFF)
        code_to_gid = {code: int(cmap_map.get(code, 0)) for code in codes}

    glyph_ids = {0}
    glyph_ids.update(code_to_gid.values())
    glyph_ids = _expand_composite_glyphs(data, glyf.offset, offsets, glyph_ids)
    ordered_glyphs = sorted(glyph_ids)
    gid_map = {gid: index for index, gid in enumerate(ordered_glyphs)}
    new_code_to_gid = {code: gid_map.get(gid, 0) for code, gid in code_to_gid.items()}

    new_glyf, new_offsets = _subset_glyf(
        data,
        glyf.offset,
        offsets,
        ordered_glyphs,
        gid_map,
    )
    hmtx_metrics = _read_hmtx(data, hmtx.offset, num_hmetrics, num_glyphs)
    new_hmtx = _build_hmtx(hmtx_metrics, ordered_glyphs)

    new_num_glyphs = len(ordered_glyphs)
    new_num_hmetrics = len(ordered_glyphs)
    maxp_data[4:6] = struct.pack(">H", new_num_glyphs)
    hhea_data[34:36] = struct.pack(">H", new_num_hmetrics)

    head_data[8:12] = b"\x00\x00\x00\x00"

    new_loca_format = index_to_loc_format
    if new_loca_format == 0 and new_offsets[-1] // 2 > 0xFFFF:
        new_loca_format = 1
    head_data[50:52] = struct.pack(">h", new_loca_format)

    if new_loca_format == 0:
        new_loca = b"".join(struct.pack(">H", offset // 2) for offset in new_offsets)
    else:
        new_loca = b"".join(struct.pack(">I", offset) for offset in new_offsets)

    new_cmap = _build_cmap_table(new_code_to_gid)

    updated = {
        b"head": bytes(head_data),
        b"hhea": bytes(hhea_data),
        b"maxp": bytes(maxp_data),
        b"hmtx": new_hmtx,
        b"loca": new_loca,
        b"glyf": new_glyf,
        b"cmap": new_cmap,
    }

    table_data: list[tuple[bytes, bytes]] = []
    for record in records:
        blob = updated.get(record.tag)
        if blob is None:
            blob = _slice_table(data, record)
        table_data.append((record.tag, blob))

    _records, font_bytes = _rebuild_font(data, table_data)
    return font_bytes, new_code_to_gid


def has_ttf_table(data: bytes, tag: bytes) -> bool:
    if len(tag) != 4:
        return False
    try:
        records = _read_table_directory(data)
    except Exception:
        return False
    return any(rec.tag == tag for rec in records)


def ensure_ttf_cmap(data: bytes, code_to_gid: dict[int, int]) -> bytes:
    """Return a font that contains a cmap table, synthesizing one when missing."""
    if has_ttf_table(data, b"cmap"):
        return data
    records = _read_table_directory(data)
    if not records:
        raise PsTypeError("invalid TrueType data")
    cmap_map = {
        int(code): int(gid)
        for code, gid in code_to_gid.items()
        if 0 <= int(code) <= 0xFFFF and int(gid) >= 0
    }
    if not cmap_map:
        raise PsTypeError("cannot synthesize cmap without code map")
    table_data: list[tuple[bytes, bytes]] = []
    inserted = False
    for record in records:
        if not inserted and record.tag > b"cmap":
            table_data.append((b"cmap", _build_cmap_table(cmap_map)))
            inserted = True
        table_data.append((record.tag, _slice_table(data, record)))
    if not inserted:
        table_data.append((b"cmap", _build_cmap_table(cmap_map)))
    _records, rebuilt = _rebuild_font(data, table_data)
    return rebuilt


def _read_table_directory(data: bytes) -> list[_TableRecord]:
    if len(data) < 12:
        raise PsTypeError("invalid TrueType data")
    num_tables = _read_uint16(data, 4)
    offset = 12
    records: list[_TableRecord] = []
    for _ in range(num_tables):
        tag = data[offset:offset + 4]
        checksum = _read_uint32(data, offset + 4)
        table_offset = _read_uint32(data, offset + 8)
        length = _read_uint32(data, offset + 12)
        records.append(_TableRecord(tag, checksum, table_offset, length))
        offset += 16
    return records


def _rebuild_font(data: bytes, table_data: list[tuple[bytes, bytes]]) -> tuple[list[_TableRecord], bytes]:
    num_tables = len(table_data)
    search_range = 2 ** int(math.floor(math.log(num_tables, 2)))
    search_range *= 16
    entry_selector = int(math.log(search_range / 16, 2)) if search_range else 0
    range_shift = num_tables * 16 - search_range
    scaler_type = data[:4]

    records: list[_TableRecord] = []
    offset = 12 + num_tables * 16
    blobs: list[bytes] = []
    for tag, blob in table_data:
        offset = _align4(offset)
        checksum = _calc_checksum(blob)
        records.append(_TableRecord(tag, checksum, offset, len(blob)))
        blobs.append((offset, blob))
        offset += len(blob)

    header = bytearray()
    header.extend(scaler_type)
    header.extend(struct.pack(">HHHH", num_tables, search_range, entry_selector, range_shift))
    for record in records:
        header.extend(record.tag)
        header.extend(struct.pack(">III", record.checksum, record.offset, record.length))

    total_len = _align4(offset)
    font_bytes = bytearray(total_len)
    font_bytes[:len(header)] = header
    for table_offset, blob in blobs:
        font_bytes[table_offset:table_offset + len(blob)] = blob
    _update_checksum_adjustment(font_bytes, records)
    return records, bytes(font_bytes)


def _slice_table(data: bytes, record: _TableRecord) -> bytes:
    end = min(len(data), record.offset + record.length)
    if record.offset >= len(data) or end < record.offset:
        return b""
    return data[record.offset:end]


def _read_loca(
    data: bytes,
    offset: int,
    index_to_loc_format: int,
    num_glyphs: int,
) -> list[int]:
    count = num_glyphs + 1
    offsets: list[int] = []
    if index_to_loc_format == 0:
        for i in range(count):
            entry_offset = offset + i * 2
            if entry_offset + 2 > len(data):
                offsets.append(0)
                continue
            offsets.append(_read_uint16(data, entry_offset) * 2)
    else:
        for i in range(count):
            entry_offset = offset + i * 4
            if entry_offset + 4 > len(data):
                offsets.append(0)
                continue
            offsets.append(_read_uint32(data, entry_offset))
    return offsets


def _expand_composite_glyphs(
    data: bytes,
    glyf_offset: int,
    offsets: list[int],
    glyph_ids: set[int],
) -> set[int]:
    queue = list(glyph_ids)
    seen = set(glyph_ids)
    max_gid = len(offsets) - 1
    while queue:
        gid = queue.pop()
        if gid < 0 or gid >= max_gid:
            continue
        start = offsets[gid]
        end = offsets[gid + 1]
        if start == end:
            continue
        comps = _composite_components(
            data,
            glyf_offset + start,
            glyf_offset + end,
        )
        for comp in comps:
            if comp not in seen:
                seen.add(comp)
                queue.append(comp)
    return seen


def _composite_components(data: bytes, offset: int, glyph_end: int) -> list[int]:
    if offset + 10 > glyph_end:
        return []
    number_of_contours = _read_int16(data, offset)
    if number_of_contours >= 0:
        return []
    pos = offset + 10
    components: list[int] = []
    flags = 0x0020
    while flags & 0x0020:
        if pos + 4 > glyph_end:
            break
        flags = _read_uint16(data, pos)
        pos += 2
        glyph_id = _read_uint16(data, pos)
        pos += 2
        components.append(glyph_id)
        if flags & 0x0001:
            pos += 4
        else:
            pos += 2
        if flags & 0x0008:
            pos += 2
        elif flags & 0x0040:
            pos += 4
        elif flags & 0x0080:
            pos += 8
        if not (flags & 0x0020) and (flags & 0x0100):
            if pos + 2 > glyph_end:
                break
            instr_len = _read_uint16(data, pos)
            pos += 2 + instr_len
    return components


def _subset_glyf(
    data: bytes,
    glyf_offset: int,
    offsets: list[int],
    glyph_ids: list[int],
    gid_map: dict[int, int],
) -> tuple[bytes, list[int]]:
    new_offsets = [0]
    new_data = bytearray()
    max_gid = len(offsets) - 1
    for gid in glyph_ids:
        if gid < 0 or gid >= max_gid:
            new_offsets.append(len(new_data))
            continue
        start = glyf_offset + offsets[gid]
        end = glyf_offset + offsets[gid + 1]
        if start < 0 or end < start or start > len(data) or end > len(data):
            glyph_data = b""
        else:
            glyph_data = data[start:end]
        if glyph_data:
            glyph_data = _remap_composite_glyph(glyph_data, gid_map)
        new_data.extend(glyph_data)
        if len(new_data) % 4 != 0:
            new_data.extend(b"\x00" * (_align4(len(new_data)) - len(new_data)))
        new_offsets.append(len(new_data))
    return bytes(new_data), new_offsets


def _read_hmtx(
    data: bytes,
    offset: int,
    num_hmetrics: int,
    num_glyphs: int,
) -> list[tuple[int, int]]:
    metrics: list[tuple[int, int]] = []
    advance = 0
    for _ in range(num_hmetrics):
        if offset + 4 > len(data):
            break
        advance = _read_uint16(data, offset)
        lsb = _read_int16(data, offset + 2)
        metrics.append((advance, lsb))
        offset += 4
    if num_hmetrics == 0:
        advance = 0
    for _ in range(len(metrics), num_glyphs):
        if offset + 2 > len(data):
            lsb = 0
        else:
            lsb = _read_int16(data, offset)
        metrics.append((advance, lsb))
        offset += 2
    return metrics


def _build_hmtx(
    metrics: list[tuple[int, int]],
    glyph_ids: list[int],
) -> bytes:
    output = bytearray()
    for gid in glyph_ids:
        if 0 <= gid < len(metrics):
            advance, lsb = metrics[gid]
        else:
            advance, lsb = 0, 0
        output.extend(struct.pack(">Hh", int(advance), int(lsb)))
    return bytes(output)


def _remap_composite_glyph(glyph_data: bytes, gid_map: dict[int, int]) -> bytes:
    if len(glyph_data) < 10:
        return glyph_data
    number_of_contours = _read_int16(glyph_data, 0)
    if number_of_contours >= 0:
        return glyph_data
    data = bytearray(glyph_data)
    pos = 10
    flags = 0x0020
    while flags & 0x0020:
        if pos + 4 > len(data):
            break
        flags = _read_uint16(data, pos)
        pos += 2
        glyph_id = _read_uint16(data, pos)
        new_gid = gid_map.get(glyph_id, 0)
        data[pos:pos + 2] = struct.pack(">H", new_gid)
        pos += 2
        if flags & 0x0001:
            pos += 4
        else:
            pos += 2
        if flags & 0x0008:
            pos += 2
        elif flags & 0x0040:
            pos += 4
        elif flags & 0x0080:
            pos += 8
        if not (flags & 0x0020) and (flags & 0x0100):
            if pos + 2 > len(data):
                break
            instr_len = _read_uint16(data, pos)
            pos += 2 + instr_len
    return bytes(data)


def _build_cmap_table(code_to_gid: dict[int, int]) -> bytes:
    codes = sorted(code_to_gid.keys())
    if not codes:
        codes = [0xFFFF]
    segments = [(code, code) for code in codes if code != 0xFFFF]
    segments.append((0xFFFF, 0xFFFF))
    seg_count = len(segments)
    seg_count_x2 = seg_count * 2
    search_range = 2 * (2 ** int(math.floor(math.log(seg_count, 2)))) if seg_count else 0
    entry_selector = int(math.log(search_range / 2, 2)) if search_range else 0
    range_shift = seg_count_x2 - search_range

    end_codes = [end for _, end in segments]
    start_codes = [start for start, _ in segments]
    id_deltas: list[int] = []
    id_range_offsets: list[int] = []

    for start, _end in segments:
        if start == 0xFFFF:
            id_deltas.append(1)
        else:
            glyph_id = int(code_to_gid.get(start, 0))
            id_deltas.append((glyph_id - start) & 0xFFFF)
        id_range_offsets.append(0)

    fmt4 = bytearray()
    fmt4.extend(struct.pack(">HHHHHHH", 4, 0, 0, seg_count_x2, search_range, entry_selector, range_shift))
    fmt4.extend(struct.pack(">%dH" % seg_count, *end_codes))
    fmt4.extend(struct.pack(">H", 0))
    fmt4.extend(struct.pack(">%dH" % seg_count, *start_codes))
    fmt4.extend(struct.pack(">%dH" % seg_count, *[delta & 0xFFFF for delta in id_deltas]))
    fmt4.extend(struct.pack(">%dH" % seg_count, *id_range_offsets))
    length = len(fmt4)
    fmt4[2:4] = struct.pack(">H", length)

    cmap = bytearray()
    cmap.extend(struct.pack(">HH", 0, 1))
    cmap.extend(struct.pack(">HHI", 3, 1, 12))
    cmap.extend(fmt4)
    return bytes(cmap)


def _parse_cmap_table(data: bytes, offset: int) -> dict[int, int]:
    if offset + 4 > len(data):
        return {}
    version = _read_uint16(data, offset)
    if version != 0:
        return {}
    num_tables = _read_uint16(data, offset + 2)
    candidates: list[tuple[int, int]] = []
    for i in range(num_tables):
        record_offset = offset + 4 + i * 8
        if record_offset + 8 > len(data):
            continue
        platform_id = _read_uint16(data, record_offset)
        encoding_id = _read_uint16(data, record_offset + 2)
        sub_offset = _read_uint32(data, record_offset + 4)
        if platform_id == 3 and encoding_id == 10:
            candidates.append((0, offset + sub_offset))
        elif platform_id == 3 and encoding_id == 1:
            candidates.append((1, offset + sub_offset))
        elif platform_id == 0:
            candidates.append((2, offset + sub_offset))
        elif platform_id == 3 and encoding_id == 0:
            # Symbol cmap (eg Webdings, Wingdings).
            candidates.append((3, offset + sub_offset))
    for _, chosen_offset in sorted(candidates, key=lambda item: item[0]):
        if chosen_offset + 2 > len(data):
            continue
        fmt = _read_uint16(data, chosen_offset)
        if fmt == 4:
            return _parse_cmap_format4(data, chosen_offset)
        if fmt == 12:
            return _parse_cmap_format12(data, chosen_offset)
    return {}


def _parse_cmap_format4(data: bytes, offset: int) -> dict[int, int]:
    if offset + 14 > len(data):
        return {}
    seg_count = _read_uint16(data, offset + 6) // 2
    end_offset = offset + 14
    end_codes = [_read_uint16(data, end_offset + i * 2) for i in range(seg_count)]
    start_offset = end_offset + seg_count * 2 + 2
    start_codes = [_read_uint16(data, start_offset + i * 2) for i in range(seg_count)]
    delta_offset = start_offset + seg_count * 2
    deltas = [_read_int16(data, delta_offset + i * 2) for i in range(seg_count)]
    range_offset = delta_offset + seg_count * 2
    range_offsets = [_read_uint16(data, range_offset + i * 2) for i in range(seg_count)]
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
    if offset + 16 > len(data):
        return {}
    num_groups = _read_uint32(data, offset + 12)
    cmap: dict[int, int] = {}
    group_offset = offset + 16
    for i in range(num_groups):
        start = group_offset + i * 12
        if start + 12 > len(data):
            break
        start_char, end_char, start_glyph = struct.unpack(
            ">III", data[start:start + 12]
        )
        for code in range(start_char, end_char + 1):
            cmap[int(code)] = int(start_glyph + (code - start_char))
    return cmap


def _update_checksum_adjustment(font_bytes: bytearray, records: Iterable[_TableRecord]) -> None:
    head = next((rec for rec in records if rec.tag == b"head"), None)
    if head is None:
        return
    head_offset = head.offset
    if head_offset + 12 > len(font_bytes):
        return
    font_bytes[head_offset + 8:head_offset + 12] = b"\x00\x00\x00\x00"
    checksum = _calc_checksum(bytes(font_bytes))
    adjustment = (0xB1B0AFBA - checksum) & 0xFFFFFFFF
    font_bytes[head_offset + 8:head_offset + 12] = struct.pack(">I", adjustment)


def _calc_checksum(data: bytes) -> int:
    padded = data + b"\x00" * ((_align4(len(data)) - len(data)) % 4)
    total = 0
    for i in range(0, len(padded), 4):
        total = (total + _read_uint32(padded, i)) & 0xFFFFFFFF
    return total


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _read_uint16(data: bytes, offset: int) -> int:
    return struct.unpack(">H", data[offset:offset + 2])[0]


def _read_uint32(data: bytes, offset: int) -> int:
    return struct.unpack(">I", data[offset:offset + 4])[0]


def _read_int16(data: bytes, offset: int) -> int:
    return struct.unpack(">h", data[offset:offset + 2])[0]
