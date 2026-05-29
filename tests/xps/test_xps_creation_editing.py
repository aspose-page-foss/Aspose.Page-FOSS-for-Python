import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import unittest
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.xps.document import XpsDocument
from aspose.page.xps.editing import XpsFixedPage, XpsPath


class TestXpsCreationEditing(unittest.TestCase):
    def test_create_document_with_path(self) -> None:
        doc = XpsDocument.create()
        page = doc.add_page(200, 100)
        page.elements.append(XpsPath(data="M 0,0 L 10,0 Z", fill="#FF0000"))
        data = doc.save()
        with ZipFile(BytesIO(data)) as archive:
            page_parts = [name for name in archive.namelist() if name.endswith(".fpage")]
            self.assertEqual(len(page_parts), 1)
            xml = archive.read(page_parts[0])
        root = ET.fromstring(xml)
        path_nodes = root.findall(".//{*}Path")
        self.assertEqual(len(path_nodes), 1)

    def test_insert_remove_pages_updates_package(self) -> None:
        doc = XpsDocument.create()
        doc.add_page(100, 100)
        doc.add_page(200, 200)
        doc.insert_page(1, XpsFixedPage(50, 50))
        doc.remove_page(0)
        data = doc.save()
        with ZipFile(BytesIO(data)) as archive:
            page_parts = [name for name in archive.namelist() if name.endswith(".fpage")]
        self.assertEqual(len(page_parts), 2)

    def test_edit_existing_xps_preserves_pages(self) -> None:
        path = Path("testdata/xps/integration/Simple.xps")
        doc = XpsDocument.from_file(str(path))
        doc.add_page(100, 100)
        data = doc.save()
        with ZipFile(BytesIO(data)) as archive:
            page_parts = [name for name in archive.namelist() if name.endswith(".fpage")]
        self.assertGreaterEqual(len(page_parts), 2)


if __name__ == "__main__":
    unittest.main()
