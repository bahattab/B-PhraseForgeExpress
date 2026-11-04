"""Find sentences written again and again in e-mails (PhraseExpress's Outlook analysis):
the user's own text without quotes, counting per mail, .eml/.mbox files, a fake Outlook,
and the Suggestions dialog."""
import mailbox
import os
import sys
import types
from email.message import EmailMessage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from phraseforge import mail_analysis as ma
from phraseforge.db import Store
from phraseforge.models import Phrase

THANKS = "Thank you for your quick reply."
CALL = "Please call me if you have any questions."
AR = "شكرًا لتواصلكم معنا، سنرد عليكم قريبًا."


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def mails(n=3):
    """n mails sharing THANKS, CALL and the Arabic sentence, each quoting an earlier mail."""
    out = []
    for i in range(n):
        out.append(f"Dear Mr. Customer{i},\r\n\r\n{THANKS} The order {1000 + i} ships today. {CALL}\r\n"
                   f"{AR}\r\n\r\nFrom: Someone <a@b.c>\r\nSent: Monday\r\nSubject: order\r\n\r\n"
                   f"Quoted text that must not count, it appears in every mail.\r\n")
    return out


# ---------------------------------------------------------------- the user's own text
def test_own_text_drops_quotes_headers_and_signature():
    body = ("Hello team,\nSee below.\n> quoted inline line\nMore of my text.\n"
            "On Mon, 3 Nov 2026 at 10:00, Ann <ann@x.org> wrote:\n> old\n")
    assert ma.own_text(body) == "Hello team,\nSee below.\nMore of my text."
    assert ma.own_text("Mine.\n-----Original Message-----\nTheirs.") == "Mine."
    assert ma.own_text("Mine.\n-- \nJohn Smith, Sales") == "Mine."
    assert ma.own_text("Mine.\n________________________________\nFrom: X\nSent: Y") == "Mine."
    arabic = "نصي أنا.\nمن: أحمد\nأرسل: الاثنين\nالموضوع: طلب\nنص مقتبس"
    assert ma.own_text(arabic) == "نصي أنا."
    # a line that only starts with "From:" but is not a reply header stays
    assert ma.own_text("From: the warehouse, as agreed.\nThanks.") == "From: the warehouse, as agreed.\nThanks."


def test_sentences_split_on_latin_and_arabic_marks():
    got = ma.sentences("Hi. Thank you for your order! Is the address right? هل وصلك الطلب؟ نعم وصل بحمد الله.\n"
                       "12345 67890 1111\nshort")
    assert got == ["Thank you for your order!", "Is the address right?", "هل وصلك الطلب؟", "نعم وصل بحمد الله."]


def test_analyze_counts_each_sentence_once_per_mail():
    bodies = mails(3) + [f"{THANKS} {THANKS} {THANKS}"]          # repeated inside one mail counts once
    found, n = ma.analyze(bodies, min_count=3)
    assert n == 4
    assert found == [(THANKS, 4), (CALL, 3), (AR, 3)]
    assert all("Quoted text" not in s for s, _c in found)
    assert all("order 100" not in s for s, _c in found)               # differs per mail
    found, _ = ma.analyze(mails(2), min_count=3)
    assert found == []


def test_analyze_skips_existing_phrases_and_keeps_first_spelling():
    bodies = ["please confirm the delivery date.", "Please confirm the delivery date.",
              "Please  confirm the delivery date."]
    found, _ = ma.analyze(bodies, min_count=3)
    assert found == [("please confirm the delivery date.", 3)]
    found, _ = ma.analyze(bodies, min_count=3, known=["Please confirm   the delivery date."])
    assert found == []


def test_analyze_can_be_cancelled():
    seen = []

    def progress(n):
        seen.append(n)
        return n < 2
    _found, n = ma.analyze(mails(5), progress=progress)
    assert seen == [1, 2] and n == 2


def test_analyze_into_store_uses_settings_and_does_not_double(store):
    store.set_setting("learning.min_count", "2")
    store.add_phrase(Phrase("Call", CALL))
    assert ma.analyze_into(store, mails(2)) == (2, 2)            # THANKS + AR; CALL is a phrase already
    assert {s["text"]: s["count"] for s in store.suggestions(1)} == {THANKS: 2, AR: 2}
    ma.analyze_into(store, mails(2))                             # the same mails again
    assert {s["text"]: s["count"] for s in store.suggestions(1)} == {THANKS: 2, AR: 2}
    store.dismiss_suggestion(THANKS)
    ma.analyze_into(store, mails(4))
    assert {s["text"]: s["count"] for s in store.suggestions(1)} == {AR: 4}


def test_merge_keeps_the_higher_count_of_typed_suggestions(store):
    for _ in range(5):
        store.bump_suggestion(THANKS)
    store.merge_suggestions({THANKS: 3, CALL: 4})
    assert {s["text"]: s["count"] for s in store.suggestions(1)} == {THANKS: 5, CALL: 4}
    store.merge_suggestions({})


# ---------------------------------------------------------------- mail files
def eml(text=None, html=None, subject="s"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "me@example.org", "you@example.org", subject
    if text is not None:
        m.set_content(text)
    if html is not None:
        if text is None:
            m.set_content(html, subtype="html")
        else:
            m.add_alternative(html, subtype="html")
    return m


def test_html_text_leaves_out_quoted_parts():
    html = ("<html><head><style>p{color:red}</style></head><body><p>My answer.</p><div>Second&nbsp;line<br>"
            "third</div><div class=\"gmail_quote\"><p>Their text</p><blockquote>older</blockquote></div>"
            "<blockquote type=cite>quoted</blockquote><p>After.</p></body></html>")
    text = ma.html_text(html)
    assert [x for x in text.split("\n") if x] == ["My answer.", "Second line", "third", "After."]


def test_eml_and_mbox_files(tmp_path):
    a = tmp_path / "a.eml"
    a.write_bytes(bytes(eml(text=f"{AR}\n{THANKS}")))                 # UTF-8, encoded by the email package
    b = tmp_path / "b.eml"
    b.write_bytes(bytes(eml(html=f"<p>{THANKS}</p><blockquote>{CALL}</blockquote>")))
    c = tmp_path / "c.eml"
    c.write_bytes(bytes(eml(text=f"{THANKS}\n", html="<p>ignored, the plain part wins</p>")))
    box_path = tmp_path / "Sent"                                    # Thunderbird: no extension
    box = mailbox.mbox(str(box_path))
    for i in range(2):
        box.add(eml(text=f"{CALL} Mail {i}.", subject=f"m{i}"))
    box.flush()
    box.close()
    bodies = list(ma.file_messages([a, b, c, box_path]))
    assert len(bodies) == 5
    assert AR in bodies[0] and CALL not in bodies[1] and "ignored" not in bodies[2]
    found, n = ma.analyze(bodies, min_count=2)
    assert n == 5 and dict(found) == {THANKS: 3, CALL: 2}


def test_unreadable_mail_files_raise_a_clear_error(tmp_path):
    with pytest.raises(ma.MailSourceError, match="not a mail file"):
        list(ma.file_messages([tmp_path / "x.pdf"]))
    with pytest.raises(ma.MailSourceError, match="missing.eml"):
        list(ma.file_messages([tmp_path / "missing.eml"]))


# ---------------------------------------------------------------- Outlook (COM fake)
class FakeItem:
    def __init__(self, body, cls=43):
        self.Body, self.Class = body, cls


class FakeItems:
    def __init__(self, items):
        self.items, self.i, self.sorted = items, 0, None

    def Sort(self, key, descending):
        self.sorted = (key, descending)

    def GetFirst(self):
        self.i = 0
        return self.GetNext()

    def GetNext(self):
        if self.i >= len(self.items):
            return None
        self.i += 1
        return self.items[self.i - 1]


@pytest.fixture
def outlook(monkeypatch):
    items = FakeItems([FakeItem(b) for b in mails(3)[:1]] + [FakeItem("meeting", cls=53)]
                      + [FakeItem(b) for b in mails(3)[1:]])
    state = {"folder": None, "items": items, "fail": False}

    class Namespace:
        def GetDefaultFolder(self, n):
            state["folder"] = n
            return types.SimpleNamespace(Items=items)

    class App:
        def GetNamespace(self, name):
            assert name == "MAPI"
            return Namespace()

    def dispatch(progid):
        if state["fail"]:
            raise OSError("Invalid class string")
        assert progid == "Outlook.Application"
        return App()
    client = types.ModuleType("win32com.client")
    client.Dispatch = dispatch
    pkg = types.ModuleType("win32com")
    pkg.client = client
    monkeypatch.setitem(sys.modules, "win32com", pkg)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    return state


def test_outlook_sent_items_newest_first_mail_items_only(outlook):
    assert ma.outlook_available()
    bodies = list(ma.outlook_messages(limit=2))
    assert outlook["folder"] == 5 and outlook["items"].sorted == ("[SentOn]", True)
    assert bodies == mails(3)[:2]                                   # the meeting request is skipped
    assert len(list(ma.outlook_messages())) == 3
    found, _ = ma.analyze(ma.outlook_messages(), min_count=3)
    assert dict(found) == {THANKS: 3, CALL: 3, AR: 3}


def test_outlook_missing_raises_a_clear_error(outlook):
    outlook["fail"] = True
    with pytest.raises(ma.MailSourceError, match="Classic Outlook"):
        list(ma.outlook_messages())


# ---------------------------------------------------------------- dialog
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_analyzes_outlook_and_files(app, store, outlook, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
    from phraseforge.ui.suggestions_dialog import SuggestionsDialog
    d = SuggestionsDialog(store)
    assert d.outlook_button.isEnabled() and d.list.count() == 0
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (500, True)))
    d.analyze_outlook()
    texts = [d.list.item(i).data(0x0100) for i in range(d.list.count())]
    assert set(texts) == {THANKS, CALL, AR}
    assert d.status.text() == "3 sentences repeated in 3 e-mails."
    p = d.create_phrase(THANKS, "ty#")
    assert store.get_phrase(p.id).content == THANKS
    # files
    f = tmp_path / "x.eml"
    f.write_bytes(bytes(eml(text="Looking forward to working with you.")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(f)] * 3, "")))
    d.analyze_files()
    assert "Looking forward to working with you." in [d.list.item(i).data(0x0100) for i in range(d.list.count())]
    # errors are shown, not raised
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    outlook["fail"] = True
    d.analyze_outlook()
    assert warned and "Outlook" in warned[0]


def test_suggestions_button_on_the_help_tab(app, store):
    from phraseforge.ui.main_window import MainWindow
    w = MainWindow(store)
    assert "Suggestions" in w.ribbon.tabs["help"].groups["Statistics"].buttons
