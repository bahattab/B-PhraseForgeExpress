"""OneNote integration with a fake OneNote.Application (never touches the real OneNote)."""
import base64
import re
import xml.etree.ElementTree as ET

import pytest

from phraseforge import onenote as on
from phraseforge.db import Store
from phraseforge.importers.onenote import import_nodes

NS = on.NS
HIER = f"""<?xml version="1.0"?>
<one:Notebooks xmlns:one="{NS}">
 <one:Notebook name="Work" ID="nb1">
  <one:SectionGroup name="Clients" ID="g1">
   <one:Section name="Acme" ID="s1">
    <one:Page ID="p1" name="Greeting" pageLevel="1"/>
    <one:Page ID="p2" name="Empty" pageLevel="1"/>
   </one:Section>
  </one:SectionGroup>
  <one:Section name="Notes" ID="s2"><one:Page ID="p3" name="Prices" pageLevel="1"/></one:Section>
  <one:SectionGroup name="OneNote_RecycleBin" ID="rb" isRecycleBin="true">
   <one:Section name="Deleted" ID="s9"><one:Page ID="p9" name="Old"/></one:Section>
  </one:SectionGroup>
 </one:Notebook>
</one:Notebooks>"""

PAGES = {
    "p1": f"""<one:Page xmlns:one="{NS}" ID="p1"><one:Title><one:OE><one:T><![CDATA[Greeting]]></one:T></one:OE></one:Title>
<one:Outline><one:OEChildren>
 <one:OE><one:T><![CDATA[Dear <span style='font-weight:bold'>client</span>,]]></one:T></one:OE>
 <one:OE><one:T><![CDATA[Thanks &amp; regards]]></one:T></one:OE>
 <one:OE><one:Image><one:OCRData><one:OCRText><![CDATA[INVOICE 42]]></one:OCRText></one:OCRData></one:Image></one:OE>
</one:OEChildren></one:Outline></one:Page>""",
    "p2": f"""<one:Page xmlns:one="{NS}" ID="p2"><one:Title><one:OE><one:T><![CDATA[Empty]]></one:T></one:OE></one:Title></one:Page>""",
    "p3": f"""<one:Page xmlns:one="{NS}" ID="p3"><one:Title><one:OE><one:T><![CDATA[Prices]]></one:T></one:OE></one:Title>
<one:Outline><one:OEChildren><one:OE><one:Table><one:Row>
 <one:Cell><one:OEChildren><one:OE><one:T><![CDATA[Item]]></one:T></one:OE></one:OEChildren></one:Cell>
 <one:Cell><one:OEChildren><one:OE><one:T><![CDATA[Price]]></one:T></one:OE></one:OEChildren></one:Cell>
</one:Row></one:Table></one:OE></one:OEChildren></one:Outline></one:Page>""",
}


class FakeApp:
    def __init__(self):
        self.updates, self.created = [], []

    def GetHierarchy(self, start, scope, schema):
        return HIER

    def GetPageContent(self, page_id, info, schema):
        return PAGES[page_id]

    def GetSpecialLocation(self, loc):
        return r"C:\Notes\Quick Notes.one"

    def OpenHierarchy(self, path, rel, cft):
        return "quick"

    def CreateNewPage(self, section_id, style):
        pid = f"new{len(self.created) + 1}"
        self.created.append((section_id, pid))
        return pid

    def UpdatePageContent(self, xml, last, schema, force):
        ET.fromstring(xml)                    # must be well-formed
        self.updates.append(xml)

    def NavigateTo(self, obj, sub, new):
        pass


@pytest.fixture
def client():
    return on.OneNote(app=FakeApp())


def test_hierarchy_paths_and_recycle_bin_skipped(client):
    nodes = client.notebooks()
    paths = [n.path for n in on.flatten(nodes, "page")]
    assert paths == ["Work/Clients/Acme/Greeting", "Work/Clients/Acme/Empty", "Work/Notes/Prices"]
    assert on.find(nodes, r"work\notes\prices").id == "p3"     # case-insensitive, backslashes ok
    assert on.find(nodes, "Prices").id == "p3"                   # unique name
    assert on.find(nodes, "s1").kind == "section"


def test_page_text_html_tables_and_ocr(client):
    assert client.page_text("Work/Clients/Acme/Greeting") == "Dear client,\nThanks & regards"
    assert "INVOICE 42" in client.page_text("p1", include_ocr=True)
    assert client.page_text("p1", include_title=True).startswith("Greeting\n\n")
    assert client.page_text("Prices") == "Item\tPrice"
    with pytest.raises(on.OneNoteError):
        client.page_text("Nope")


def test_send_to_quick_notes_page_and_section(client):
    app = client._app
    pid = client.send("Hello <world> ]]> end\nline 2")
    assert app.created == [("quick", pid)]
    xml = app.updates[-1]
    assert "Hello &lt;world&gt;" in xml and "line 2" in xml and "<one:Title>" in xml
    client.send("more", target="Work/Notes/Prices")            # page -> append, no new page
    assert len(app.created) == 1 and 'ID="p3"' in app.updates[-1]
    client.send("x", target="Work/Notes")                        # section -> new page there
    assert app.created[-1][0] == "s2"
    png = b"\x89PNG fake"
    client.send(image_png=png, target="p1")
    assert base64.b64encode(png).decode() in app.updates[-1]
    with pytest.raises(on.OneNoteError):
        client.send("x", target="Work")                          # notebooks are not targets


def test_import_sections_as_folders(client, tmp_path):
    store = Store(tmp_path / "s.db")
    seen = []
    rep = import_nodes(store, client, ["Work/Clients", "Work/Notes"], progress=lambda d, t, p: seen.append((d, t)))
    assert rep.imported == 2 and rep.skipped_empty == 1 and not rep.errors
    names = {f.name for f in store.folders()}
    assert {"OneNote", "Clients", "Acme", "Notes"} <= names
    ph = {p.description: p for p in store.phrases()}
    assert ph["Greeting"].content == "Dear client,\nThanks & regards"
    assert "onenote" in ph["Greeting"].tags
    assert seen[-1] == (3, 3)


def test_import_can_be_cancelled(client, tmp_path):
    store = Store(tmp_path / "s.db")
    rep = import_nodes(store, client, ["Work"], progress=lambda d, t, p: False)
    assert rep.cancelled and rep.imported == 0


def test_onenote_macro_uses_host(tmp_path):
    from phraseforge.host import ExpansionContext
    from phraseforge.macros import MacroEngine
    from tests.fakehost import FakeHost

    class Host(FakeHost):
        def onenote_page_text(self, ref, include_title=False, include_ocr=False):
            return f"[{ref}|{include_title}|{include_ocr}]"
    eng = MacroEngine(Host())
    assert eng.expand_to_text('{#onenote "Work/Notes/Prices" -title}', ExpansionContext()) == "[Work/Notes/Prices|True|False]"


def test_output_target_onenote_listed():
    from phraseforge import output_target
    assert "onenote" in output_target.TARGETS


def test_find_exe_falls_back_to_registered_path(tmp_path, monkeypatch):
    from phraseforge import onenote
    exe = tmp_path / "ONENOTE.EXE"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(onenote, "_registry_candidates", lambda: [str(exe)])
    monkeypatch.setattr(onenote, "_COMMON_DIRS", ())
    assert onenote.find_exe(str(tmp_path / "missing.exe")) == str(exe)
    assert onenote.find_exe(str(exe)) == str(exe)
    monkeypatch.setattr(onenote, "_registry_candidates", lambda: [])
    assert onenote.find_exe(str(tmp_path / "missing.exe")) == ""
