"""Find sentences you write again and again in your e-mails and offer them as phrases.

PhraseExpress can analyze the mails in Outlook to learn the user's frequent
text. PhraseForge does the same with the Sent Items folder of classic Outlook
(through COM; the new Outlook has no COM) or with saved mail files (.eml, .mbox),
so it also works with Thunderbird, Gmail exports and others.

Only the text the user wrote is analyzed: quoted replies ("> ...", "On ... wrote:",
Outlook's "From: / Sent:" header block, "-----Original Message-----", HTML
<blockquote>) and anything after a "-- " signature line are dropped. A sentence
counts once per e-mail, and it becomes a suggestion when it appears in at least
learning.min_count different e-mails (default 3) and is at least
learning.min_length characters long (default 12). Sentences that already are a
phrase are left out. Results go to the same Suggestions list the typing learner
fills (Store.merge_suggestions), and nothing leaves the computer.
"""
from __future__ import annotations

import email
import email.policy
import logging
import mailbox
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Iterator

MAIL_FILE_EXT = (".eml", ".mbox", ".mbx")
MAX_BODY = 1_000_000          # characters; larger bodies are pasted logs or data, not writing
log = logging.getLogger(__name__)
MAX_SENTENCE = 300
OL_FOLDERS = {"sent": 5, "inbox": 6}   # olFolderSentMail, olFolderInbox
OL_MAIL = 43                           # olMail: MailItem, not meeting requests or reports


class MailSourceError(Exception):
    """The mail source could not be read (Outlook missing, file unreadable ...)."""


# ---------------------------------------------------------------- the user's own text
_QUOTE_START = re.compile(
    r"^\s*(?:-{2,}\s*(?:Original Message|Ursprüngliche Nachricht|Message d'origine|Mensaje original|"
    r"Messaggio originale|Oorspronkelijk bericht|الرسالة الأصلية|"
    r"Forwarded message|Weitergeleitete Nachricht|Message transféré|Mensaje reenviado|"   # forwards (Gmail ...)
    r"Messaggio inoltrato|Doorgestuurd bericht|Begin forwarded message|رسالة معاد توجيهها)\s*:?\s*-{2,}"
    r"|Begin forwarded message\s*:"                               # Apple Mail
    r"|_{10,}"                                                    # Outlook on the web separator
    r"|On\b.{0,200}\bwrote:"                                      # Gmail, Apple Mail, Thunderbird
    r"|Am\b.{0,200}\bschrieb\b.{0,100}:"
    r"|Le\b.{0,200}\ba écrit\s*:"
    r"|في\b.{0,200}كتب.{0,100}:"                                  # Gmail in Arabic
    r")\s*$", re.I)
_HEADER = re.compile(r"^\s*\*?(From|De|Von|Da|Van|من|المرسل)\s*\*?\s*:", re.I)
_HEADER_NEXT = re.compile(r"^\s*\*?(?:(?:Sent|Date|Subject|To|Gesendet|Datum|Betreff|Envoyé|Objet|Enviado|Asunto|"
                          r"Para|Inviato|Data|Oggetto|Verzonden|Onderwerp|"
                          r"أرسل|تاريخ|التاريخ|الموضوع|إلى)[^:]{0,20}|A|À|An|Aan)\*?\s*:", re.I)
_SIGNATURE = re.compile(r"^--\s?$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?؟])\s+")
_LETTER = re.compile(r"[^\W\d_]")


def own_text(body: str) -> str:
    """The part of a mail body the sender wrote: quoted replies and signature removed."""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    for i, line in enumerate(lines):
        if _QUOTE_START.match(line) or _SIGNATURE.match(line):
            break
        if _HEADER.match(line) and any(_HEADER_NEXT.match(x) for x in lines[i + 1:i + 6]):
            break                                   # Outlook's reply header: From: / Sent: / To: / Subject:
        if line.lstrip().startswith(">"):
            continue                                # inline quote
        out.append(line)
    return "\n".join(out)


def sentences(text: str, min_length: int = 12) -> list[str]:
    """Candidate sentences of one mail (each line split at . ! ? ؟), whitespace normalized."""
    found = []
    for line in text.split("\n"):
        for s in _SENTENCE_SPLIT.split(line):
            s = " ".join(s.split())
            if min_length <= len(s) <= MAX_SENTENCE and _LETTER.search(s):
                found.append(s)
    return found


def analyze(bodies: Iterable[str], min_count: int = 3, min_length: int = 12,
            known: Iterable[str] = (), progress: Callable[[int], bool] | None = None) -> tuple[list[tuple[str, int]], int]:
    """([(sentence, number of mails it appears in)], mails read), most frequent first.
    progress(mails read so far) is called for each mail; returning False stops early."""
    counts: Counter[str] = Counter()
    first: dict[str, str] = {}                      # casefolded -> the first spelling seen
    n = 0
    for body in bodies:
        n += 1
        if progress is not None and progress(n) is False:
            break
        if not body or len(body) > MAX_BODY:
            continue
        seen = set()
        for s in sentences(own_text(body), min_length):
            key = s.casefold()
            if key not in seen:
                seen.add(key)
                counts[key] += 1
                first.setdefault(key, s)
    skip = {" ".join(k.split()).casefold() for k in known if k}
    out = [(first[k], c) for k, c in counts.items() if c >= max(1, min_count) and k not in skip]
    out.sort(key=lambda x: (-x[1], x[0]))
    return out, n


def analyze_into(store, bodies: Iterable[str], progress: Callable[[int], bool] | None = None) -> tuple[int, int]:
    """Analyze mails with the learning.* settings and add the results to the store's
    suggestions. Returns (suggestions found, mails read)."""
    def num(key, default):
        try:
            return int(store.setting(key, str(default)) or default)
        except ValueError:
            return default
    known = [p.content for p in store.phrases() if p.content_format == "text"]
    found, n = analyze(bodies, num("learning.min_count", 3), num("learning.min_length", 12), known, progress)
    store.merge_suggestions(dict(found))
    return len(found), n


# ---------------------------------------------------------------- mail files
class _HtmlText(HTMLParser):
    """Text of an HTML mail, without quoted parts (<blockquote>, Gmail's gmail_quote)."""
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
    MAX_DEPTH = 256
    VOID = {"br", "img", "hr", "meta", "link", "input", "col", "area", "base", "wbr", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []      # (tag, starts a skipped part)
        self.open: dict[str, int] = {}               # tag -> how often it is on the stack
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in self.VOID:
            return
        cls = " ".join(v or "" for k, v in attrs if k in ("class", "id"))
        quoted = tag in ("blockquote", "style", "script", "head", "title") or "gmail_quote" in cls \
            or "divRplyFwdMsg" in cls
        if len(self.stack) >= self.MAX_DEPTH:      # nesting this deep is not a real mail: stop tracking,
            if quoted:                             # but a quoted part still hides everything after it
                self.skip += 1
            return
        self.stack.append((tag, quoted))
        self.open[tag] = self.open.get(tag, 0) + 1
        if quoted:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if not self.open.get(tag):                  # not open: nothing to search for (keeps this linear)
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for t, quoted in self.stack[i:]:
                    self.open[t] -= 1
                    if quoted:
                        self.skip -= 1
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(html: str) -> str:
    p = _HtmlText()
    p.feed(html)
    p.close()
    return "".join(p.parts).replace("\xa0", " ")


def message_text(msg) -> str:
    """Plain text of an email.message.EmailMessage (text/plain preferred over HTML)."""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
    except Exception:
        part = None
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        try:
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:                         # a charset Python does not know
            text = payload.decode("latin-1")
    if not isinstance(text, str) or len(text) > MAX_BODY:
        return ""                                   # too big to be writing (and slow to parse)
    if part.get_content_subtype() == "html":
        text = html_text(text)
    return text


def file_messages(paths: Iterable[str | Path]) -> Iterator[str]:
    """Bodies of the mails in .eml and .mbox files."""
    pol = email.policy.default
    for path in paths:
        p = Path(path)
        ext = p.suffix.lower()
        if ext == ".eml":
            try:
                data = p.read_bytes()
            except OSError as e:
                raise MailSourceError(f"{p.name}: {e}") from e
            text = _one(lambda: message_text(email.message_from_bytes(data, policy=pol)), p.name)
            if text is not None:
                yield text
        elif ext in (".mbox", ".mbx") or (not ext and p.is_file()):
            try:
                box = mailbox.mbox(str(p), factory=lambda f: email.message_from_binary_file(f, policy=pol),
                                   create=False)
                keys = list(box.iterkeys())
            except Exception as e:
                raise MailSourceError(f"{p.name}: {e}") from e
            try:
                for key in keys:                    # one broken message is skipped, not the whole file
                    text = _one(lambda: message_text(box[key]), p.name)
                    if text is not None:
                        yield text
            finally:
                box.close()
        else:
            raise MailSourceError(f"not a mail file: {p.name}")


def _one(read: Callable[[], str], name: str) -> str | None:
    """Text of one message, or None (logged) when that message cannot be read."""
    try:
        return read()
    except Exception as e:                          # bad charset, MIME nested too deep ...
        log.warning("a message in %s was skipped: %s", name, type(e).__name__)
        return None


# ---------------------------------------------------------------- Outlook
def outlook_available() -> bool:
    try:
        import win32com.client  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def outlook_messages(limit: int = 500, folder: str = "sent") -> Iterator[str]:
    """Bodies of the newest mails in an Outlook default folder (classic Outlook, COM).
    Outlook is started if it is not running, as the user asked for the analysis."""
    try:
        import win32com.client  # type: ignore
        app = win32com.client.Dispatch("Outlook.Application")
        items = app.GetNamespace("MAPI").GetDefaultFolder(OL_FOLDERS[folder]).Items
        items.Sort("[SentOn]" if folder == "sent" else "[ReceivedTime]", True)
        item = items.GetFirst()
    except Exception as e:
        raise MailSourceError("Outlook is not available. Classic Outlook for Windows is needed; "
                              "the new Outlook cannot be automated. Save the mails as .eml files "
                              "and analyze those instead.") from e
    n = 0
    while item is not None and n < limit:
        try:
            if getattr(item, "Class", None) == OL_MAIL:
                n += 1
                yield str(item.Body or "")
        except Exception:
            pass                                    # an unreadable item (encrypted, ...) is skipped
        try:
            item = items.GetNext()
        except Exception:
            break
