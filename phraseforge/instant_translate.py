"""Instant translation of the text selected in any program (a desktop take on the "bubble"
of browser translation add-ons).

Select text anywhere, press the hotkey (Settings > Language Translation > Instant
translation): a small window opens next to the caret or mouse with the translation, made
by the engine chosen in Settings > Language Translation. From there: copy it, replace the
selection with it, swap the direction, hear it, or pick another target language.

The direction is automatic: text in the target language is translated into the second
language, so one hotkey covers both ways (Arabic <-> English by default).
"""
from __future__ import annotations

MAX_CHARS = 5000


def was_cut(text: str) -> bool:
    return len((text or "").strip()) > MAX_CHARS


LANGUAGES = ("Arabic", "English", "French", "German", "Spanish", "Italian", "Portuguese", "Turkish",
             "Persian", "Urdu", "Russian", "Chinese", "Japanese", "Korean", "Hindi", "Indonesian", "Dutch")


def target_for(text: str, to: str, back: str) -> str:
    """The language to translate into: `to`, unless the text already is in `to` (then `back`)."""
    from phraseforge import ai
    src = ai.guess_language(text)                       # 'ar' or 'en' (cheap, offline)
    if src == ai.iso_code(to)[:2] and back and back.lower() != to.lower():
        return back
    return to


FREE_CONSENT = "translate.instant_free_ok"


def check_service(settings: dict) -> None:
    """Raise ValueError unless the selection may go to the translation service. The hotkey
    works in any program, so the text must not go to MyMemory (a free online service) unless
    the user chose it, either as the engine or by allowing it here (R153)."""
    from phraseforge import ai
    provider = (settings.get("translation.provider") or "free").lower()
    if ai.translation_service(settings) != "free":
        return
    if provider != "free":
        raise ValueError(f"There is no API key for {provider}; add it in Settings > Language Translation. "
                         "The selection was not sent anywhere.")
    if settings.get(FREE_CONSENT) != "1":
        raise ValueError("Instant translation would send the selected text to MyMemory, a free online "
                         "service. Choose a translation engine in Settings > Language Translation, or "
                         "allow MyMemory under Instant translation there.")


def translate(settings: dict, text: str, to: str = "", translate_fn=None) -> tuple[str, str]:
    """(translation, target language) for the selected text. Raises ValueError for no text, or
    for a service the user did not agree to. Only the first MAX_CHARS characters are translated
    (was_cut tells)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Select some text first, then press the hotkey.")
    if translate_fn is None:
        check_service(settings)
    text = text[:MAX_CHARS]
    target = to or target_for(text, settings.get("translate.instant_to") or "Arabic",
                              settings.get("translate.instant_back") or "English")
    from phraseforge import ai
    out = (translate_fn or (lambda t, lang: ai.translate_text(settings, t, lang)))(text, target)
    return out, target
