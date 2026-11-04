"""0.5.9: PhraseExpress XML import, and phrase export to HTML / MHT."""
from phraseforge import documents
from phraseforge.db import Store
from phraseforge.importers.phraseexpress import import_any, import_xml
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind

XML_ATTRS = """<?xml version="1.0" encoding="utf-8"?>
<phraseexpress>
  <folder description="Greetings">
    <phrase description="Hi" autotext="hi" hotkey="Ctrl+1">Hello world</phrase>
    <folder description="Formal">
      <phrase description="Dear" autotext="dr">Dear Sir or Madam</phrase>
    </folder>
  </folder>
  <phrase description="Signature">Best regards</phrase>
</phraseexpress>"""

XML_CHILDREN = """<?xml version="1.0"?>
<phrases>
  <phrase>
    <description>Address</description>
    <content>1 Main St</content>
    <autotext>addr</autotext>
  </phrase>
  <phrase>
    <description>Empty</description><content></content>
  </phrase>
</phrases>"""


def _tree(store):
    out = {}
    def walk(fid, prefix):
        for f in store.folders(fid):
            out[prefix + f.name] = [p.description for p in store.phrases(f.id)]
            walk(f.id, prefix + f.name + "/")
    walk(None, "")
    return out


def test_import_xml_attributes_and_nested_folders(tmp_path):
    f = tmp_path / "export.xml"
    f.write_text(XML_ATTRS, encoding="utf-8")
    s = Store(":memory:")
    rep = import_xml(s, str(f))
    assert rep.imported == 3
    top = s.get_folder(rep.folder_id)
    tree = _tree(s)
    assert tree[top.name + "/Greetings"] == ["Hi"]
    assert tree[top.name + "/Greetings/Formal"] == ["Dear"]
    hi = next(p for p in s.phrases(next(f.id for f in s.folders(top.id) if f.name == "Greetings"))
              if p.description == "Hi")
    full = s.get_phrase(hi.id)
    assert any(t.kind == TriggerKind.AUTOTEXT and t.value == "hi" for t in full.triggers)
    assert any(t.kind == TriggerKind.HOTKEY and t.value == "Ctrl+1" for t in full.triggers)


def test_import_xml_child_elements_and_skips_empty(tmp_path):
    f = tmp_path / "c.xml"
    f.write_text(XML_CHILDREN, encoding="utf-8")
    s = Store(":memory:")
    rep = import_xml(s, str(f))
    assert rep.imported == 1 and rep.skipped == 1
    descs = [p.description for p in s.phrases(rep.folder_id)]
    assert descs == ["Address"]


def test_import_any_dispatches_xml(tmp_path):
    f = tmp_path / "x.xml"
    f.write_text(XML_ATTRS, encoding="utf-8")
    rep = import_any(Store(":memory:"), str(f))
    assert rep.imported == 3


def test_import_bad_xml_raises(tmp_path):
    f = tmp_path / "bad.xml"
    f.write_text("<not closed", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        import_xml(Store(":memory:"), str(f))


def _store_with_phrases():
    s = Store(":memory:")
    g = s.add_folder(Folder("Work"))
    s.add_phrase(Phrase("Greeting", "Hello\nSecond line", folder_id=g.id,
                        triggers=[Trigger(TriggerKind.AUTOTEXT, "hi")]))
    s.add_phrase(Phrase("عربي", "مرحبا بالعالم", folder_id=g.id))
    return s


def test_export_html(tmp_path):
    s = _store_with_phrases()
    out = tmp_path / "phrases.html"
    n = documents.export(s, s.phrases(), str(out))
    html = out.read_text(encoding="utf-8")
    assert n == 2
    assert "Greeting" in html and "Hello<br>Second line" in html
    assert 'dir="rtl"' in html and "مرحبا بالعالم" in html
    assert "hi" in html


def test_export_mht_is_valid_mime(tmp_path):
    import email
    s = _store_with_phrases()
    out = tmp_path / "phrases.mht"
    documents.export(s, s.phrases(), str(out))
    msg = email.message_from_bytes(out.read_bytes())
    assert msg.get_content_type() == "multipart/related"
    html = msg.get_payload(0).get_payload(decode=True).decode("utf-8")
    assert "Greeting" in html and "مرحبا" in html


def test_export_unknown_format_rejected(tmp_path):
    import pytest
    s = _store_with_phrases()
    with pytest.raises(ValueError):
        documents.export(s, s.phrases(), str(tmp_path / "x.zzz"))
