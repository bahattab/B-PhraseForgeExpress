

def test_translate_text_keeps_macros_and_uses_free_service_without_key():
    from phraseforge import ai
    calls = []

    def fake_free(text, to, src):
        calls.append((text, to, src))
        return f"[{text}]"
    out = ai.translate_text({}, "Dear {#input name}, thanks!\n{#date}", "Arabic", free_fn=fake_free)
    assert out == "[Dear] {#input name}[, thanks!]\n{#date}"      # macros and spacing kept
    assert all(src == "en" and to == "Arabic" for _, to, src in calls)
    # a configured AI key uses the AI engine instead
    got = ai.translate_text({"translation.provider": "openai", "ai.openai_key": "k"}, "Hi", "Arabic",
                            complete_fn=lambda t: "مرحبا")
    assert got == "مرحبا"


def test_free_translate_chunks_and_errors():
    from phraseforge import ai
    seen = []

    def get(url, params):
        seen.append(params)
        return {"responseStatus": 200, "responseData": {"translatedText": "x"}}
    long_text = ("This is a sentence. " * 60).strip()
    ai.free_translate(long_text, "Arabic", get=get)
    assert len(seen) > 1 and all(len(p["q"].encode()) <= 450 for p in seen)
    assert seen[0]["langpair"] == "en|ar"
    assert ai.guess_language("مرحبا بالعالم") == "ar" and ai.free_translate("hi", "English", "en") == "hi"
    import pytest
    with pytest.raises(ai.AIError, match="QUOTA"):
        ai.free_translate("Hello", "Arabic", get=lambda u, p: {"responseStatus": 429,
                                                               "responseDetails": "QUOTA EXCEEDED"})
