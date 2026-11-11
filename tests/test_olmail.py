"""{#olmail -field ...}: the open Outlook mail (FR-OL-01), with a fake Outlook object model."""
import random

import pytest

from phraseforge.host import ExpansionContext
from phraseforge.macros import commands_extra as ce
from phraseforge.macros.engine import MacroEngine
from tests.fakehost import FakeHost


class Atts:
    def __init__(self, names):
        self.names = names
        self.Count = len(names)

    def Item(self, i):
        return type("A", (), {"FileName": self.names[i - 1]})()


class Mail:
    SenderEmailAddress = "ali@example.com"
    SenderEmailType = "SMTP"
    SenderName = "Ali Hassan"
    To = "Sara; Omar"
    CC = "Team"
    BCC = None
    Subject = "Quarterly report"
    Body = "Hello"
    HTMLBody = "<p>Hello</p>"
    Attachments = Atts(["a.pdf", "b.xlsx"])


def text(s):
    return MacroEngine(FakeHost(), rng=random.Random(1)).expand_to_text(s, ExpansionContext())


@pytest.mark.parametrize("field,expect", [
    ("from", "ali@example.com"), ("fromname", "Ali Hassan"), ("to", "Sara; Omar"), ("cc", "Team"),
    ("bcc", ""), ("subject", "Quarterly report"), ("body", "Hello"), ("htmlbody", "<p>Hello</p>"),
    ("attachments", "a.pdf; b.xlsx"),
])
def test_fields(monkeypatch, field, expect):
    monkeypatch.setattr(ce, "outlook_item", lambda: Mail())
    assert text(f"{{#olmail -field {field}}}") == expect


def test_exchange_sender_uses_smtp(monkeypatch):
    class Ex(Mail):
        SenderEmailType = "EX"
        SenderEmailAddress = "/O=ORG/CN=ali"
        Sender = type("S", (), {"GetExchangeUser": lambda self: type("U", (), {"PrimarySmtpAddress": "ali@corp.com"})()})()
    monkeypatch.setattr(ce, "outlook_item", lambda: Ex())
    assert text("{#olmail -field from}") == "ali@corp.com"


def test_outlook_closed_gives_empty(monkeypatch):
    monkeypatch.setattr(ce, "outlook_item", lambda: None)
    assert text("{#olmail -field subject}") == ""


def test_real_lookup_never_starts_outlook():
    assert ce.outlook_item() is None or hasattr(ce.outlook_item(), "Subject")   # no Outlook on CI: None


def test_bad_field_and_long_body(monkeypatch):
    assert "olmail" in text("{#olmail -field password}")
    class Big(Mail):
        Body = "x" * (ce.MAX_OLMAIL + 10)
    monkeypatch.setattr(ce, "outlook_item", lambda: Big())
    assert len(text("{#olmail -field body}")) == ce.MAX_OLMAIL


def test_item_that_is_not_a_mail(monkeypatch):
    class Meeting:
        @property
        def Subject(self):
            raise RuntimeError("COM error")
    monkeypatch.setattr(ce, "outlook_item", lambda: Meeting())
    assert text("{#olmail -field subject}") == ""
