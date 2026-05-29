from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from aspose.page.common.render_model import (
    ClipCommand,
    ImageCommand,
    PathCommand,
    RenderDocument,
    RenderPage,
    StateRestoreCommand,
    StateSaveCommand,
    TextCommand,
)
from aspose.page.common.render_model import Matrix


@dataclass
class BBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def update(self, x: float, y: float) -> None:
        self.x_min = min(self.x_min, x)
        self.y_min = min(self.y_min, y)
        self.x_max = max(self.x_max, x)
        self.y_max = max(self.y_max, y)

    def merge(self, other: "BBox | None") -> None:
        if other is None:
            return
        self.update(other.x_min, other.y_min)
        self.update(other.x_max, other.y_max)


def dump_render_model(document: RenderDocument, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pages": [_page_summary(page, index) for index, page in enumerate(document.pages, start=1)],
    }
    totals = {"path": 0, "text": 0, "image": 0, "clip": 0, "save": 0, "restore": 0}
    for page in payload["pages"]:
        for key in totals:
            totals[key] += page["counts"][key]
    payload["totals"] = totals
    payload["bbox_mode"] = "axis_aligned_approx"
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _page_summary(page: RenderPage, index: int) -> dict:
    counts = {"path": 0, "text": 0, "image": 0, "clip": 0, "save": 0, "restore": 0}
    overall_bbox = None
    type_bboxes: dict[str, BBox | None] = {"path": None, "text": None, "image": None}

    for command in page.commands:
        if isinstance(command, PathCommand):
            counts["path"] += 1
            bbox = _path_bbox(command)
            overall_bbox = _merge_bbox(overall_bbox, bbox)
            type_bboxes["path"] = _merge_bbox(type_bboxes["path"], bbox)
        elif isinstance(command, TextCommand):
            counts["text"] += 1
            bbox = _text_bbox(command)
            overall_bbox = _merge_bbox(overall_bbox, bbox)
            type_bboxes["text"] = _merge_bbox(type_bboxes["text"], bbox)
        elif isinstance(command, ImageCommand):
            counts["image"] += 1
            bbox = _image_bbox(command)
            overall_bbox = _merge_bbox(overall_bbox, bbox)
            type_bboxes["image"] = _merge_bbox(type_bboxes["image"], bbox)
        elif isinstance(command, ClipCommand):
            counts["clip"] += 1
        elif isinstance(command, StateSaveCommand):
            counts["save"] += 1
        elif isinstance(command, StateRestoreCommand):
            counts["restore"] += 1

    return {
        "index": index,
        "size": {"width": page.width, "height": page.height},
        "counts": counts,
        "bbox": _bbox_payload(overall_bbox),
        "type_bbox": {key: _bbox_payload(value) for key, value in type_bboxes.items()},
    }


def _path_bbox(command: PathCommand) -> BBox | None:
    points = []
    for segment in command.path.segments:
        if segment.points:
            points.extend(segment.points)
    if not points:
        return None
    bbox = BBox(points[0].x, points[0].y, points[0].x, points[0].y)
    for point in points[1:]:
        bbox.update(point.x, point.y)
    return bbox


def _text_bbox(command: TextCommand) -> BBox | None:
    width = max(0.0, command.font_size * 0.6 * len(command.text))
    height = max(0.0, command.font_size)
    return _rect_bbox(command.matrix, width, height)


def _image_bbox(command: ImageCommand) -> BBox | None:
    return _rect_bbox(command.matrix, float(command.width), float(command.height))


def _rect_bbox(matrix: Matrix, width: float, height: float) -> BBox | None:
    points = [
        _apply_matrix(matrix, 0.0, 0.0),
        _apply_matrix(matrix, width, 0.0),
        _apply_matrix(matrix, width, height),
        _apply_matrix(matrix, 0.0, height),
    ]
    bbox = BBox(points[0][0], points[0][1], points[0][0], points[0][1])
    for x, y in points[1:]:
        bbox.update(x, y)
    return bbox


def _apply_matrix(matrix: Matrix, x: float, y: float) -> tuple[float, float]:
    return (
        matrix.a * x + matrix.c * y + matrix.e,
        matrix.b * x + matrix.d * y + matrix.f,
    )


def _merge_bbox(current: BBox | None, other: BBox | None) -> BBox | None:
    if other is None:
        return current
    if current is None:
        return BBox(other.x_min, other.y_min, other.x_max, other.y_max)
    current.merge(other)
    return current


def _bbox_payload(bbox: BBox | None) -> dict | None:
    if bbox is None:
        return None
    return asdict(bbox)
