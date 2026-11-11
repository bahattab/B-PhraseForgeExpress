"""DeepL glossary sync (FR-AI-04)."""
import json

import httpx
import pytest

from phraseforge import ai

REAL_CLIENT = httpx.Client


class FakeDeepL:
    def __init__(self):
        self.glossaries = {}
        self.calls = []
        self.n = 0

    def handler(self, r: httpx.Request):
        self.calls.append((r.method, r.url.path))
        assert r.headers["authorization"] == "DeepL-Auth-Key k:fx"
        assert r.url.host == "api-free.deepl.com"
        if r.method == "GET":
            return httpx.Response(200, json={"glossaries": [dict(g, ready=True) for g in self.glossaries.values()]})
        if r.method == "POST":
            body = json.loads(r.content)
            self.n += 1
            gid = f"g{self.n}"
            self.glossaries[gid] = {"glossary_id": gid, **body}
            return httpx.Response(201, json={"glossary_id": gid})
        if r.method == "DELETE":
            self.glossaries.pop(r.url.path.rsplit("/", 1)[1], None)
            return httpx.Response(204)
        return httpx.Response(405)


@pytest.fixture
def deepl(monkeypatch):
    fake = FakeDeepL()
    monkeypatch.setattr(ai, "_GLOSSARY_IDS", {})          # each test talks to a new fake account
    monkeypatch.setattr(ai, "_GLOSSARY_REFUSED", {})
    monkeypatch.setattr(ai.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(fake.handler),
                                                                    timeout=kw.get("timeout")))
    sent = {}

    def post(url, headers, payload, timeout):
        sent.update(url=url, payload=payload)
        return {"translations": [{"text": "مرحبا"}]}
    monkeypatch.setattr(ai, "_post", post)
    return fake, sent


def settings(text="Invoice=فاتورة\nbad line\nInvoice=again\nTab\tx=y", langs=("English", "Arabic")):
    return {"ai.deepl_key": "k:fx", "translation.glossaries": json.dumps({"Billing": text}),
            "translation.glossary_langs": json.dumps({"Billing": list(langs)} if langs else {})}


def test_entries():
    assert ai.glossary_entries("a=b\n=x\nc=\nd = e \na=z\nt\tab=q") == [("a", "b"), ("d", "e")]


def test_upload_then_reuse(deepl):
    fake, _ = deepl
    gid = ai.sync_deepl_glossary(settings(), "Billing")
    g = fake.glossaries[gid]
    assert g["name"].startswith("PhraseForge: Billing #")
    assert (g["source_lang"], g["target_lang"], g["entries"], g["entries_format"]) == ("en", "ar", "Invoice\tفاتورة", "tsv")
    assert ai.sync_deepl_glossary(settings(), "Billing") == gid          # unchanged: no new upload
    assert [c for c in fake.calls if c[0] == "POST"] == [("POST", "/v2/glossaries")]


def test_changed_glossary_replaces_old_copy(deepl):
    fake, _ = deepl
    old = ai.sync_deepl_glossary(settings(), "Billing")
    new = ai.sync_deepl_glossary(settings("Invoice=فاتورة\nTax=ضريبة"), "Billing")
    assert new != old and list(fake.glossaries) == [new]


def test_other_glossaries_on_account_are_left_alone(deepl):
    fake, _ = deepl
    fake.glossaries["mine"] = {"glossary_id": "mine", "name": "Someone else's"}
    fake.glossaries["pf2"] = {"glossary_id": "pf2", "name": "PhraseForge: Billing2 #abc"}
    ai.sync_deepl_glossary(settings(), "Billing")
    assert "mine" in fake.glossaries and "pf2" in fake.glossaries


def test_translate_uses_matching_glossary(deepl):
    fake, sent = deepl
    assert ai.deepl_translate(settings(), "Invoice", "Arabic") == "مرحبا"
    assert sent["payload"]["glossary_id"] in fake.glossaries
    assert sent["payload"]["source_lang"] == "EN" and sent["payload"]["target_lang"] == "AR"


def test_translate_other_language_skips_glossary(deepl):
    fake, sent = deepl
    ai.deepl_translate(settings(), "Invoice", "German")
    assert "glossary_id" not in sent["payload"] and fake.calls == []


def test_glossary_without_languages_is_not_sent(deepl):
    fake, sent = deepl
    ai.deepl_translate(settings(langs=None), "Invoice", "Arabic")
    assert "glossary_id" not in sent["payload"] and fake.calls == []
    with pytest.raises(ai.AIError, match="languages"):
        ai.deepl_translate(settings(langs=None), "Invoice", "Arabic", glossary="Billing")


def test_named_glossary_failure_is_reported(deepl, monkeypatch):
    def boom(*a, **k):
        raise ai.AIError("DeepL HTTP 456: quota")
    monkeypatch.setattr(ai, "_deepl_call", boom)
    with pytest.raises(ai.AIError, match="456"):
        ai.deepl_translate(settings(), "x", "Arabic", glossary="Billing")
    _fake, sent = deepl
    ai.deepl_translate(settings(), "x", "Arabic")                        # automatic: translate anyway
    assert "glossary_id" not in sent["payload"]


def test_macro_passes_glossary(monkeypatch):
    import random
    from phraseforge.host import ExpansionContext
    from phraseforge.macros import MacroEngine
    from tests.fakehost import FakeHost
    seen = {}
    monkeypatch.setattr(ai, "deepl_translate", lambda st, text, to, src="", glossary="": seen.update(g=glossary) or "ok")
    host = FakeHost({"translation.provider": "deepl", "ai.deepl_key": "k"})
    out = MacroEngine(host, rng=random.Random(1)).expand_to_text('{#translate hi -to Arabic -glossary "Billing"}',
                                                                 ExpansionContext())
    assert out == "ok" and seen == {"g": "Billing"}
