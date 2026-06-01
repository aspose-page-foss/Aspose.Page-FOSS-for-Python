# Aspose.Page for Python: Convert PS, EPS, and XPS to PDF, PNG, and JPEG

Aspose.Page FOSS for Python is an open-source Python document conversion library for developers who need PostScript (PS), Encapsulated PostScript (EPS), and XPS conversion in backend services, automation pipelines, and document workflows.

## Why Aspose.Page for Python

- Convert PS/EPS to PDF in Python
- Convert PS/EPS to PNG and JPEG in Python
- Convert XPS to PDF in Python
- Convert XPS to PNG and JPEG in Python
- Integrate conversion workflows through MCP server tools

## Installation

### Install package

```bash
pip install -e .
```

### Install optional dependencies by scenario

For MCP server hosting:

```bash
pip install fastmcp
```

For PS/EPS to image and XPS to image conversion:

```bash
pip install skia-python
```

For running tests:

```bash
pip install pypdf pypdfium2 Pillow
```

## Currently Available Features

- PS/EPS to PDF conversion
- PS/EPS to PNG/JPEG conversion
- XPS to PDF conversion
- XPS to PNG/JPEG conversion

## Quick Start

### Convert PS to PDF

```python
from aspose.page.ps.document import PsDocument

ps = PsDocument.from_file("input.ps")
output_pdf = ps.to_pdf()

with open("output.pdf", "wb") as f:
    f.write(output_pdf)
```

### Convert EPS to PNG

```python
from aspose.page.ps.document import PsDocument
from aspose.page.ps.output import ImageSaveOptions

eps = PsDocument.from_file("input.eps")
output_png = eps.to_image(ImageSaveOptions(format="png", dpi=150))

with open("output.png", "wb") as f:
    f.write(output_png)
```

### Convert XPS to PDF

```python
from aspose.page.xps.document import XpsDocument

xps = XpsDocument.from_file("input.xps")
output_pdf = xps.to_pdf()

with open("output.pdf", "wb") as f:
    f.write(output_pdf)
```

### Convert XPS to JPEG

```python
from aspose.page.ps.output import ImageSaveOptions
from aspose.page.xps.document import XpsDocument

xps = XpsDocument.from_file("input.xps")
output_jpeg = xps.to_image(ImageSaveOptions(format="jpeg", dpi=150))

with open("output.jpg", "wb") as f:
    f.write(output_jpeg)
```

## Example Results

### XPS mb03 rendered via xps2pdf (PDF page rendered to PNG)

![mb03 xps2pdf result](test-out/xps/xps2pdf/integration/mb03.png)

### XPS mb03 rendered via xps2image

![mb03 xps2image result](test-out/xps/xps2image/integration/mb03.png)

### PS/EPS image conversion sample

![PS to image sample](test-out/ps/ps2image/functional/COLOR13/RGB1.png)

## MCP Server

MCP tools currently exposed:

- `ps_to_pdf`
- `ps_to_image`
- `xps_to_pdf`
- `xps_to_image`
- `eps_metadata`

Run MCP server:

```python
from aspose.page.mcp import create_server

server = create_server()
server.run(host="127.0.0.1", port=8000)
```

Important notes:

- `FastMCP` is required to start the MCP server.
- `skia-python` is required for image conversion flows (`ps_to_image`, `xps_to_image`).

## Build and Test (Developers)

Sync dependencies:

```bash
make sync
```

Run tests:

```bash
make test
```

Run MCP-focused checks:

```bash
python3 -m unittest tests.mcp.test_handlers tests.mcp.test_server
```

Build distribution artifacts:

```bash
make build
```

## License

MIT. See `LICENSE` for the full text.
