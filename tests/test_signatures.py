"""Signature manager: signatures in their folder, dated footers, random quotes, the
{#signature} macro, export to Outlook's signature folder and the dialog."""
import os
import random
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from phraseforge import signatures as sig
from phraseforge.db import Store
from phraseforge.host import ExpansionContext
from phraseforge.macros import MacroEngine
from phraseforge.models import Phrase
from tests.fakehost import FakeHost

AR_SIG = "مع خالص التحية،\nأحمد"


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def add(store, sub, text, desc=None):
    f = sig.subfolder(store, sub, create=True)
    return store.add_phrase(Phrase(desc or text[:30], text, folder_id=f.id))


def run(store, text, when=datetime(2026, 6, 1), fmt="", seed=1):
    ctx = ExpansionContext(content_format=fmt)
    return MacroEngine(FakeHost(), store, clock=lambda: when, rng=random.Random(seed)).expand_to_text(text, ctx)


# ---------------------------------------------------------------- dates
@pytest.mark.parametrize("start,end,day,shown", [
    ("12-15", "01-05", date(2026, 12, 20), True),        # wraps over New Year
    ("12-15", "01-05", date(2027, 1, 3), True),
    ("12-15", "01-05", date(2026, 6, 1), False),
    ("03-01", "03-31", date(2026, 3, 31), True),
    ("03-01", "03-31", date(2026, 4, 1), False),
    ("", "", date(2026, 4, 1), True),                    # no dates: always
    ("2026-11-01", "2026-11-10", date(2026, 11, 5), True),
    ("2026-11-01", "2026-11-10", date(2027, 11, 5), False),   # a full date does not repeat
    ("2026-11-01", "", date(2030, 1, 1), True),
    ("", "02-29", date(2026, 2, 28), True),
    ("13-01", "", date(2026, 1, 1), False),              # broken date: never shown
])
def test_footer_date_ranges(start, end, day, shown):
    assert sig.is_active(start, end, day) is shown


def test_footer_dates_are_validated_and_cleared(store):
    f = add(store, sig.FOOTERS, "Happy holidays!")
    with pytest.raises(ValueError):
        sig.set_footer_dates(store, f.id, "12-32", "")
    sig.set_footer_dates(store, f.id, "12-15", "01-05")
    assert sig.footer_dates(store) == {f.id: ("12-15", "01-05")}
    sig.set_footer_dates(store, f.id, "", "")
    assert sig.footer_dates(store) == {}
    store.set_setting("signature.footer_dates", "not json")
    assert sig.footer_dates(store) == {}


# ---------------------------------------------------------------- signatures
def test_first_signature_becomes_default_and_default_can_change(store):
    assert sig.default(store) is None and sig.compose(store) is None
    a = sig.new_signature(store, "Work", "Best regards,\nAli")
    b = sig.new_signature(store, "Private", "Cheers, Ali")
    assert [p.description for p in sig.signatures(store)] == ["Private", "Work"]
    assert sig.default(store).id == a.id
    sig.set_default(store, b.id)
    assert sig.default(store).id == b.id
    store.delete_phrase(b.id)
    assert sig.default(store).id == a.id               # a deleted default falls back
    assert sig.find(store, "work").id == a.id and sig.find(store, "nope") is None
    add(store, sig.FOOTERS, "A footer")                 # footers and quotes are not signatures
    assert [p.description for p in sig.signatures(store)] == ["Work"]


def test_compose_adds_active_footers_and_a_random_quote(store):
    sig.new_signature(store, "Work", "Best regards,\nAli\n")
    xmas = add(store, sig.FOOTERS, "Happy holidays!")
    add(store, sig.FOOTERS, "Visit us at booth 12.")
    sig.set_footer_dates(store, xmas.id, "12-15", "01-05")
    assert sig.compose(store, today=date(2026, 6, 1)) == ("Best regards,\nAli\n\nVisit us at booth 12.", "text")
    text, _ = sig.compose(store, today=date(2026, 12, 24))
    assert text.endswith("Happy holidays!\n\nVisit us at booth 12.")
    add(store, sig.QUOTES, "Simplicity is the soul of efficiency.")
    assert "Simplicity" not in sig.compose(store, today=date(2026, 6, 1))[0]
    store.set_setting("signature.random_quote", "1")
    assert sig.compose(store, today=date(2026, 6, 1))[0].endswith("Simplicity is the soul of efficiency.")


def test_compose_mixes_formatted_and_plain_parts_and_language_versions(store):
    s = sig.new_signature(store, "Work", "<p><b>Ali</b> &amp; Co</p>")
    store.update_phrase(Phrase("Work", "<p><b>Ali</b> &amp; Co</p>", folder_id=s.folder_id, id=s.id,
                               content_format="html"))
    store.set_phrase_version(s.id, "ar", AR_SIG, "text")
    add(store, sig.FOOTERS, 'Tel. 1 < 2 "x"')
    html, fmt = sig.compose(store, today=date(2026, 1, 1))
    assert fmt == "html" and html == '<p><b>Ali</b> &amp; Co</p><br><br>Tel. 1 &lt; 2 "x"'
    text, fmt = sig.compose(store, lang="ar", today=date(2026, 1, 1))
    assert fmt == "text" and text.startswith(AR_SIG)


# ---------------------------------------------------------------- macro
def test_signature_macro_runs_macros_inside(store):
    sig.new_signature(store, "Work", "Best regards,\n{#upper ali}")
    sig.new_signature(store, "Short", "-- A")
    assert run(store, "Hello\n\n{#signature}") == "Hello\n\nBest regards,\nALI"
    assert run(store, '{#signature "Short"}') == "-- A"
    assert "not found" in run(store, '{#signature "Missing"}')
    assert run(store, "{#signature -lang fr}") == "Best regards,\nALI"   # no such version: default


def test_signature_macro_in_formatted_and_plain_phrases(store):
    sig.new_signature(store, "Work", "Best regards,\nأحمد")
    assert run(store, "{#signature}", fmt="html") == 'Best regards,<br><span dir="rtl">أحمد</span>'
    s = sig.default(store)
    store.update_phrase(Phrase("Work", "<p>Hi<br>there</p>", folder_id=s.folder_id, id=s.id, content_format="html"))
    assert run(store, "{#signature}", fmt="html") == "<p>Hi<br>there</p>"
    assert run(store, "{#signature}") == "Hi\nthere"


def test_signature_that_inserts_itself_stops(store):
    sig.new_signature(store, "Loop", "A {#signature}")
    assert run(store, "{#signature}") == "A "


def test_no_signature_inserts_nothing(store):
    assert run(store, "x{#signature}y") == "xy"


def test_imported_signature_cannot_run_privileged_macros(store):
    s = sig.new_signature(store, "Work", '{#run "calc.exe"}')
    store.quarantine(s.id, "imported")
    assert "blocked" in run(store, "{#signature}")


# ---------------------------------------------------------------- Outlook
def test_export_writes_htm_rtf_and_txt_for_outlook(store, tmp_path):
    sig.new_signature(store, "Work: Sales/EU", "Best regards,\n{#upper ali}")
    sig.new_signature(store, "عربي", AR_SIG)
    add(store, sig.FOOTERS, "Always here")
    expand = lambda content, fmt: run(store, content, fmt=fmt)
    written = sig.export_outlook(store, expand, tmp_path)
    assert sorted(p.name for p in written) == ["Work_ Sales_EU.htm", "عربي.htm"]
    htm = (tmp_path / "Work_ Sales_EU.htm").read_text(encoding="utf-8")
    assert "charset=utf-8" in htm and "Best regards,<br>ALI<br><br>Always here" in htm and 'dir="rtl"' not in htm
    assert (tmp_path / "Work_ Sales_EU.txt").read_text(encoding="utf-16") == "Best regards,\nALI\n\nAlways here"
    rtf = (tmp_path / "Work_ Sales_EU.rtf").read_text(encoding="ascii")
    assert rtf.startswith("{\\rtf1") and "ALI" in rtf
    ar = (tmp_path / "عربي.htm").read_text(encoding="utf-8")
    assert '<body dir="rtl">' in ar and "أحمد" in ar
    from phraseforge.importers.files import rtf_to_text
    assert "أحمد" in rtf_to_text((tmp_path / "عربي.rtf").read_text(encoding="ascii"))
    only = sig.export_outlook(store, expand, tmp_path / "one", ids=[sig.find(store, "عربي").id])
    assert [p.name for p in only] == ["عربي.htm"]


def test_outlook_folder_and_file_names(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert sig.outlook_dir() == tmp_path / "Microsoft" / "Signatures"
    assert sig.file_name('a<b>c:"d"|e?*.') == "a_b_c__d__e__"
    assert sig.file_name("...") == "Signature"


class FakeWinreg:
    HKEY_CURRENT_USER, REG_SZ = "HKCU", 1

    def __init__(self):
        self.values, self.closed = {}, 0

    def CreateKey(self, root, path):
        return (root, path)

    def SetValueEx(self, key, name, _reserved, kind, value):
        self.values[(key[1], name)] = (kind, value)

    def CloseKey(self, key):
        self.closed += 1


def test_set_outlook_default_writes_new_and_reply_signature():
    reg = FakeWinreg()
    sig.set_outlook_default("Work: EU", winreg=reg)
    assert reg.values == {(sig.OUTLOOK_MAIL_SETTINGS, "NewSignature"): (1, "Work_ EU"),
                          (sig.OUTLOOK_MAIL_SETTINGS, "ReplySignature"): (1, "Work_ EU")}
    reg = FakeWinreg()
    sig.set_outlook_default("Work", reply=False, winreg=reg)
    assert list(reg.values) == [(sig.OUTLOOK_MAIL_SETTINGS, "NewSignature")] and reg.closed == 1


def test_preview_expand_runs_macros_without_prompts(store):
    expand = sig.preview_expand(store)
    assert expand("Hi {#upper x}", "text") == "Hi X"
    assert expand("<b>{#upper x}</b>", "html") == "<b>X</b>"


# ---------------------------------------------------------------- dialog
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_lists_previews_exports_and_sets_outlook_default(app, store, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    from phraseforge.ui.signatures_dialog import SignaturesDialog
    edited = []
    expand = lambda content, fmt: run(store, content, fmt=fmt)
    d = SignaturesDialog(store, on_edit=edited.append, expand=expand)
    assert d.list.count() == 0
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Work", True)))
    d.new()
    p = sig.find(store, "Work")
    assert edited == [p.id] and "{#ad name}" in p.content               # the template uses ActiveDirectory
    d = SignaturesDialog(store, on_edit=edited.append, expand=expand)
    assert d.list.count() == 1 and d.list.item(0).text() == "Work  (default)"
    store.update_phrase(Phrase("Work", "Best regards,\n{#upper ali}", folder_id=p.folder_id, id=p.id))
    d.refresh()
    assert "ALI" in d.preview.toPlainText()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Happy holidays!", True)))
    d.new_footer()
    assert d.footer_list.count() == 1 and "always" in d.footer_list.item(0).text()
    d.quote.setChecked(True)
    assert store.setting("signature.random_quote") == "1"
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Less is more.", True)))
    d.new_quote()
    assert "Less is more." in d.preview.toPlainText()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes))
    reg = FakeWinreg()
    written = d.export_outlook(target=tmp_path, winreg=reg)
    assert [w.name for w in written] == ["Work.htm"] and "Work" in asked[0]
    assert reg.values[(sig.OUTLOOK_MAIL_SETTINGS, "NewSignature")] == (1, "Work")


def test_signatures_button_and_macro_menu_entry(app, store):
    from phraseforge.ui import macro_ui
    from phraseforge.ui.main_window import MainWindow
    w = MainWindow(store)
    assert "Signatures" in w.ribbon.tabs["phrases"].groups["Insert"].buttons
    assert ("@direct", "E-mail signature", "{#signature}") in macro_ui.OUTLOOK
    assert macro_ui.display_name('{#signature "Work"}') == "Signature: Work"
