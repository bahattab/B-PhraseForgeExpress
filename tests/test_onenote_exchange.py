"""0.5.9 exchange: import a .one file, export phrases to OneNote, publish OneNote to a format."""
import xml.etree.ElementTree as ET

import pytest

from phraseforge import onenote as on
from phraseforge.db import Store
from phraseforge.importers.onenote import export_to_onenote, import_one_file
from phraseforge.models import Folder, Phrase

NS = on.NS
HIER = f"""<?xml version="1.0"?>
<one:Notebooks xmlns:one="{NS}">
 <one:Section name="Quick Notes" ID="sFile">
  <one:Page ID="pf1" name="First" pageLevel="1"/>
  <one:Page ID="pf2" name="Second" pageLevel="1"/>
 </one:Section>
</one:Notebooks>"""
PAGE = f"""<one:Page xmlns:one="{NS}" ID="{{id}}"><one:Title><one:OE><one:T><![CDATA[{{t}}]]></one:T></one:OE></one:Title>
<one:Outline><one:OEChildren><one:OE><one:T><![CDATA[{{t}} body]]></one:T></one:OE></one:OEChildren></one:Outline></one:Page>"""


class FakeApp:
    def __init__(self):
        self.created, self.published = [], []

    def GetHierarchy(self, start, scope, schema):
        return HIER

    def GetPageContent(self, page_id, info, schema):
        return PAGE.format(id=page_id, t={"pf1": "First", "pf2": "Second"}[page_id])

    def OpenHierarchy(self, path, rel, cft):
        self.opened = (path, cft)
        return "sFile"

    def CreateNewPage(self, section_id, style):
        pid = f"np{len(self.created) + 1}"
        self.created.append([section_id, pid, None])
        return pid

    def UpdatePageContent(self, xml, last, schema, force):
        root = ET.fromstring(xml)                      # well-formed
        title = root.find(f".//{{{NS}}}Title//{{{NS}}}T")
        if self.created:
            self.created[-1][2] = title.text if title is not None else ""

    def Publish(self, hid, path, fmt, dummy):
        self.published.append((hid, path, fmt))


@pytest.fixture
def client():
    return on.OneNote(app=FakeApp())


def test_import_one_file(client, tmp_path):
    one = tmp_path / "Quick Notes.one"
    one.write_bytes(b"onefile")
    s = Store(":memory:")
    rep = import_one_file(s, client, str(one))
    assert client.app.opened == (str(one), on.CFT_NONE)
    descs = {p.description for p in s.phrases(rep.folder_id)}
    assert descs == {"First", "Second"} and rep.imported == 2


def test_import_missing_one_file_errors(client):
    s = Store(":memory:")
    with pytest.raises(on.OneNoteError):
        import_one_file(s, client, "/no/such/file.one")


def test_export_phrases_to_onenote_section(client, tmp_path):
    s = Store(":memory:")
    f = s.add_folder(Folder("Greetings"))
    sub = s.add_folder(Folder("Formal", parent_id=f.id))
    s.add_phrase(Phrase("Hi", "Hello there", folder_id=f.id))
    s.add_phrase(Phrase("Dear", "Dear Sir", folder_id=sub.id))
    out = tmp_path / "Greetings.one"
    rep = export_to_onenote(s, client, str(out), folder_id=f.id)
    assert client.app.opened == (str(out), on.CFT_SECTION)
    titles = [c[2] for c in client.app.created]
    assert "Hi" in titles and "Formal / Dear" in titles and rep.imported == 2


def test_publish_formats(client, tmp_path):
    out = tmp_path / "notebook.pdf"
    client.publish("nb1", str(out), "pdf")
    assert client.app.published == [("nb1", str(out), on.PF["pdf"])]
    with pytest.raises(on.OneNoteError):
        client.publish("nb1", str(tmp_path / "x.zzz"), "zzz")


def test_publish_format_table_matches_extensions():
    for label, key in on.PUBLISH_FORMATS:
        assert key in on.PF
        assert f"*.{key}" in label.lower() or (key == "docx" and "docx" in label.lower())
