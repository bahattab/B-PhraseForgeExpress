"""0.5.9 OneNote exchange from the main window (fake OneNote client, no real OneNote)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase
from phraseforge.onenote import Node


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeClient:
    def __init__(self):
        self.pages, self.published = [], []
        self.section = Node("sX", "Imported", "section", "Imported",
                            [Node("pX", "Page one", "page", "Imported/Page one")])

    def open_file(self, path):
        self.opened = path
        return "sX"

    def notebooks(self):
        return [self.section]

    def page_xml(self, page_id):
        from phraseforge.onenote import NS
        return (f'<one:Page xmlns:one="{NS}" ID="{page_id}"><one:Title><one:OE><one:T>'
                f'<![CDATA[Page one]]></one:T></one:OE></one:Title><one:Outline><one:OEChildren>'
                f'<one:OE><one:T><![CDATA[body text]]></one:T></one:OE></one:OEChildren></one:Outline></one:Page>')

    def new_section_file(self, path):
        self.new_path = path
        return "sNew"

    def create_page(self, section_id, title, text="", image_png=None):
        self.pages.append((title, text))
        return f"p{len(self.pages)}"

    def publish(self, hid, path, fmt):
        self.published.append((hid, path, fmt))
        return path


def test_import_onenote_file(app, tmp_path):
    from phraseforge.ui import main_window as mw
    s = Store(":memory:")
    w = mw.MainWindow(s)
    fc = FakeClient()
    one = tmp_path / "Quick Notes.one"
    one.write_bytes(b"x")
    w.import_onenote_file(str(one), client_factory=lambda: fc, show_message=False)
    assert fc.opened == str(one)
    assert any(p.description == "Page one" for p in s.phrases(w.selected_folder_id()))


def test_export_onenote_section(app, tmp_path):
    from phraseforge.ui import main_window as mw
    s = Store(":memory:")
    f = s.add_folder(Folder("Letters"))
    s.add_phrase(Phrase("Hi", "Hello", folder_id=f.id))
    w = mw.MainWindow(s)
    w.select_folder(f.id)
    fc = FakeClient()
    out = tmp_path / "Letters.one"
    rep = w.export_onenote_section(str(out), client_factory=lambda: fc, show_message=False)
    assert fc.new_path == str(out) and fc.pages == [("Hi", "Hello")] and rep.imported == 1


def test_export_onenote_file_publishes(app, tmp_path):
    from phraseforge.ui import main_window as mw
    w = mw.MainWindow(Store(":memory:"))
    fc = FakeClient()
    out = tmp_path / "export.pdf"
    res = w.export_onenote_file(ref="Imported", path=str(out), fmt="pdf",
                                client_factory=lambda: fc, show_message=False)
    assert res == str(out) and fc.published == [("sX", str(out), "pdf")]
