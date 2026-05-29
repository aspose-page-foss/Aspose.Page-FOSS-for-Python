import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import unittest
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aspose.page.xps.document import XpsDocument


PRINT_TICKET_XML = (
    "<psf:PrintTicket xmlns:psf='http://schemas.microsoft.com/windows/2003/08/printing/printschemaframework'/>"
)
PRINT_TICKET_TYPE = "http://schemas.microsoft.com/xps/2005/06/printticket"


class TestXpsPrintTickets(unittest.TestCase):
    def _rels_types(self, archive: ZipFile, rels_path: str) -> list[str]:
        if rels_path not in archive.namelist():
            return []
        rels_xml = ET.fromstring(archive.read(rels_path))
        return [rel.get("Type") for rel in rels_xml.findall(".//{*}Relationship") if rel.get("Type")]

    def test_add_document_print_ticket(self) -> None:
        doc = XpsDocument.create()
        doc.add_page(100, 100)
        data = doc.save()
        doc = XpsDocument.from_bytes(data)
        doc.set_print_ticket("document", PRINT_TICKET_XML)
        updated = doc.save()
        with ZipFile(BytesIO(updated)) as archive:
            rels_path = "Documents/1/_rels/FixedDoc.fdoc.rels"
            types = self._rels_types(archive, rels_path)
            self.assertIn(PRINT_TICKET_TYPE, types)
            targets = [
                rel.get("Target")
                for rel in ET.fromstring(archive.read(rels_path)).findall(".//{*}Relationship")
                if rel.get("Type") == PRINT_TICKET_TYPE
            ]
            self.assertTrue(targets)
            self.assertIn(f"Documents/1/{targets[0]}", archive.namelist())

    def test_remove_page_print_ticket(self) -> None:
        doc = XpsDocument.create()
        doc.add_page(100, 100)
        doc = XpsDocument.from_bytes(doc.save())
        doc.set_print_ticket("page", PRINT_TICKET_XML, page_index=0)
        with ZipFile(BytesIO(doc.save())) as archive:
            rels_path = "Documents/1/Pages/_rels/1.fpage.rels"
            types = self._rels_types(archive, rels_path)
            self.assertIn(PRINT_TICKET_TYPE, types)
        doc = XpsDocument.from_bytes(doc.save())
        doc.remove_print_ticket("page", page_index=0)
        updated = doc.save()
        with ZipFile(BytesIO(updated)) as archive:
            rels_path = "Documents/1/Pages/_rels/1.fpage.rels"
            types = self._rels_types(archive, rels_path)
            self.assertNotIn(PRINT_TICKET_TYPE, types)

    def test_read_print_ticket(self) -> None:
        doc = XpsDocument.create()
        doc.add_page(100, 100)
        doc = XpsDocument.from_bytes(doc.save())
        doc.set_print_ticket("job", PRINT_TICKET_XML)
        tickets = doc.get_print_tickets()
        self.assertTrue(any(ticket.scope.value == "job" for ticket in tickets))
        self.assertTrue(any("PrintTicket" in ticket.xml for ticket in tickets))


if __name__ == "__main__":
    unittest.main()
