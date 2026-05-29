# Aspose.Page FOSS for Python

Aspose.Page FOSS for Python is an open-source toolkit for working with PostScript/EPS and XPS content. It provides a PostScript interpreter core, a shared render model, and PDF 1.4 output generation without third-party dependencies.

## Features (Current)
- PS/EPS interpreter core (tokenizer, parser, execution context)
- Render model and PS/EPS conversion pipeline
- XPS interpreter core
- Render model and XPSconversion pipeline
- PDF 1.4 writer from the render model
- Raster image output (PNG, JPEG, TIFF, BMP) from the render model
- MCP

## Requirements
- Python 3.10+

## Quick Start

```python
from aspose.page.common.render_model import (
    Paint,
    Rect,
    RenderModelBuilder,
    StrokeStyle,
    rect_path,
)
from aspose.page.pdf.writer import PdfMetadata, PdfWriter

builder = RenderModelBuilder()
builder.set_default_page_size(300, 200)
path = rect_path(Rect(10, 10, 100, 60))
stroke = StrokeStyle(1.0, 0, 0, 10.0, [], 0.0)
paint = Paint("DeviceRGB", (0, 0, 0))

builder.add_path(path, stroke, paint)
render_doc = builder.document()

metadata = PdfMetadata(
    title="",
    creator="",
    producer="Aspose.Page FOSS for Python",
    creation_date="D:20260101000000",
    mod_date="D:20260101000000",
    trapped=False,
)

pdf_bytes = PdfWriter(metadata).write(render_doc)

with open("output.pdf", "wb") as f:
    f.write(pdf_bytes)
```

```python
from aspose.page.ps.document import PsDocument
from aspose.page.ps.output import ImageSaveOptions

doc = PsDocument.from_file("testdata/ps/integration/minimal.ps")
png_bytes = doc.to_image(ImageSaveOptions(format="png", dpi=72))

with open("output.png", "wb") as f:
    f.write(png_bytes)
```

## Running Tests

```bash
make test
```

## Build System (uv)

The project uses `uv` as the main build/developer tool.

### Setup and Sync

```bash
make sync
```

### Run Tests

```bash
make test
```

### Build Wheel and Source Distribution

```bash
make build
```

Build artifacts are created in `dist/`.

### Post Codex Metrics (Manual)

```bash
make post-metrics-dry-run METRICS_RUN_ID=run-001 METRICS_TOKEN_USAGE=1234 METRICS_API_CALLS_COUNT=42
make post-metrics METRICS_RUN_ID=run-001 METRICS_STATUS=success METRICS_JOB_TYPE="Debug FONTS10"
```

You can also post from a JSON template:

```bash
make post-metrics-from-file-dry-run METRICS_PAYLOAD_FILE=backlog/docs/metrics_api_v1_template.json
make post-metrics-from-file METRICS_PAYLOAD_FILE=backlog/docs/metrics_api_v1_template.json
```

### Legacy setuptools Compatibility

For tools that still invoke setuptools directly:

```bash
python3 setup.py --name
```

## Project Layout

- `src/aspose/page/ps` — PS/EPS interpreter core
- `src/aspose/page/common` — render model
- `src/aspose/page/pdf` — PDF 1.4 writer
- `src/aspose/page/image` — raster output
- `tests` — unit tests

## License

[MIT](./LICENSE.txt)
