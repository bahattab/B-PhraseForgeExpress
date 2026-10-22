"""Macro commands added to cover every PhraseExpress-style macro dialog.

Host features that HostServices doesn't define yet are looked up with getattr
and degrade gracefully (documented per command):
  notify(title, text, on_click="")            -> None
  ask_buttons(text, title, buttons)           -> str   (clicked button)
  pick_file(title, directory, filename, ext, save) -> str   ("" = cancelled)
  set_clipboard_files(paths: list[str])       -> None
  focus_window(process, title, state)         -> bool
  set_keyboard_layout(language)               -> bool
"""
from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path

from phraseforge.host import Cancelled, KeyAction
from phraseforge.macros.registry import MacroError, macro, register


def _arg(args, i, default=""):
    return args[i] if len(args) > i else default


def _flag(opts, key) -> bool:
    v = opts.get(key)
    return v is not None and v.strip().lower() not in ("0", "false", "no", "off")


def _esc(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\t", "\t")


def _host(rt, name):
    return getattr(rt.host, name, None)


# ====================================================================== text operations
@macro("strpos", "Text", '{#strpos text sub -regex -i}',
       "1-based position of the first occurrence of sub in text (0 if not found).")
def _strpos(rt, args, opts):
    text, sub = _arg(args, 0), _arg(args, 1)
    if _flag(opts, "regex"):
        m = re.search(sub, text, re.I if _flag(opts, "i") else 0)
        return str(m.start() + 1 if m else 0)
    if _flag(opts, "i"):
        text, sub = text.lower(), sub.lower()
    return str(text.find(sub) + 1)


@macro("lastpos", "Text", '{#lastpos text sub -regex -i}',
       "1-based position of the last occurrence of sub in text (0 if not found).")
def _lastpos(rt, args, opts):
    text, sub = _arg(args, 0), _arg(args, 1)
    if _flag(opts, "regex"):
        ms = list(re.finditer(sub, text, re.I if _flag(opts, "i") else 0))
        return str(ms[-1].start() + 1 if ms else 0)
    if _flag(opts, "i"):
        text, sub = text.lower(), sub.lower()
    return str(text.rfind(sub) + 1)


@macro("sentence", "Text", "{#sentence text}", "Begin sentences with uppercase.")
def _sentence(rt, args, opts):
    t = " ".join(args)
    return re.sub(r"(^\s*|[.!?؟]\s+)(\w)", lambda m: m.group(1) + m.group(2).upper(), t)


@macro("ucfirst", "Text", "{#ucfirst text}", "UPPER CASE first character.")
def _ucfirst(rt, args, opts):
    t = " ".join(args)
    return t[:1].upper() + t[1:]


@macro("lcfirst", "Text", "{#lcfirst text}", "lower case first character.")
def _lcfirst(rt, args, opts):
    t = " ".join(args)
    return t[:1].lower() + t[1:]


@macro("ucwords", "Text", "{#ucwords text}", "UPPER CASE first char of each word.")
def _ucwords(rt, args, opts):
    return re.sub(r"\b(\w)", lambda m: m.group(1).upper(), " ".join(args))


@macro("lcwords", "Text", "{#lcwords text}", "lower case first char of each word.")
def _lcwords(rt, args, opts):
    return re.sub(r"\b(\w)", lambda m: m.group(1).lower(), " ".join(args))


@macro("ltrim", "Text", "{#ltrim text}", "Trim leading spaces.")
def _ltrim(rt, args, opts):
    return " ".join(args).lstrip()


@macro("rtrim", "Text", "{#rtrim text}", "Trim trailing spaces.")
def _rtrim(rt, args, opts):
    return " ".join(args).rstrip()


@macro("ascii", "Text", "{#ascii 65}", "Character with the given ASCII/Unicode code (decimal, or 0x hex).")
def _ascii(rt, args, opts):
    code = _arg(args, 0, "32").strip()
    try:
        return chr(int(code, 16) if code.lower().startswith("0x") else int(code))
    except ValueError as e:
        raise MacroError(f"bad character code {code!r}") from e


# ====================================================================== output
@macro("gender", "Output", '{#gender -male "He" -female "She" -neutral "It"}',
       "Gender-O-Matic: outputs the male/female/neutral form. The gender comes from variable 'gender' "
       "(m/f/n) or is asked once per expansion.")
def _gender(rt, args, opts):
    g = (rt.get_var("gender") or "").strip().lower()[:1]
    if g not in ("m", "f", "n"):
        picked = rt.host.choose("Gender", ["Male", "Female", "Neutral"])
        g = (picked[0] if picked else "Neutral")[:1].lower()
        rt.set_var("gender", g, "local")
    return {"m": opts.get("male", _arg(args, 0)), "f": opts.get("female", _arg(args, 1)),
            "n": opts.get("neutral", _arg(args, 2))}[g]


@macro("notify", "Output", '{#notify "Title" "Text" -click "output when clicked"}',
       "Show a desktop notification (no output).")
def _notify(rt, args, opts):
    fn = _host(rt, "notify")
    title, text = _arg(args, 0), _arg(args, 1, opts.get("text", ""))
    if fn:
        fn(title, text, opts.get("click", ""))
    else:
        rt.host.message(text, title)
    return None


@macro("outputfile", "Output", '{#outputfile "C:\\out.txt" "contents" -append -open -encoding utf-8}',
       "Write contents to a file (no output). -open opens it afterwards. -template copies a .dot(x) "
       "template to the target first (contents are appended as text for .txt targets only).")
def _outputfile(rt, args, opts):
    path = os.path.expandvars(_arg(args, 0))
    if not path:
        raise MacroError("no target file")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tpl = opts.get("template")
    if tpl:
        import shutil
        shutil.copyfile(os.path.expandvars(tpl), path)
    else:
        mode = "a" if _flag(opts, "append") else "w"
        with open(path, mode, encoding=opts.get("encoding", "utf-8"), newline="") as fh:
            fh.write(_arg(args, 1, opts.get("contents", "")))
    if _flag(opts, "open"):
        rt.host.open_target(opts.get("openpath") or path)
    return None


@macro("pastefile", "Output", '{#pastefile "C:\\file.pdf"}',
       "Paste a file (as a file, like Explorer copy/paste) via the clipboard.")
def _pastefile(rt, args, opts):
    path = os.path.expandvars(_arg(args, 0))
    if not Path(path).exists():
        raise MacroError(f"file not found: {path}")
    fn = _host(rt, "set_clipboard_files")
    if fn is None:
        raise MacroError("pasting files is not supported by this host")
    fn([path])
    return KeyAction("ctrl+v")


@macro("pastemethod", "Output", "{#pastemethod auto|type|paste -delay 0}",
       "Override the output method for this phrase (place at the beginning). -delay = ms between keys.")
def _pastemethod(rt, args, opts):
    method = _arg(args, 0, "auto").lower()
    if method not in ("auto", "type", "paste"):
        raise MacroError(f"unknown paste method {method!r}")
    # read by the output layer: ctx.paste_method / ctx.key_delay_ms
    setattr(rt.ctx, "paste_method", method)
    setattr(rt.ctx, "key_delay_ms", int(opts.get("delay", "0") or 0))
    return None


@macro("setlanguage", "Output", '{#setlanguage "ar-SA"}',
       "Switch the keyboard layout of the target application (language tag or name).")
def _setlanguage(rt, args, opts):
    fn = _host(rt, "set_keyboard_layout")
    if fn is None:
        raise MacroError("switching keyboard layout is not supported by this host")
    fn(_arg(args, 0))
    return None


# ====================================================================== user input
@macro("fileselect", "Forms", '{#fileselect -title "Pick a file" -ext txt -file name -dir "C:\\"}',
       "Show a file open dialog and output the chosen path.")
def _fileselect(rt, args, opts):
    return _pick_file(rt, opts, save=False)


@macro("filesave", "Forms", '{#filesave -title "Save as" -ext txt -file name -dir "C:\\"}',
       "Show a file save dialog and output the chosen path.")
def _filesave(rt, args, opts):
    return _pick_file(rt, opts, save=True)


def _pick_file(rt, opts, save):
    fn = _host(rt, "pick_file")
    title = opts.get("title", "Save file" if save else "Select file")
    if fn:
        p = fn(title, os.path.expandvars(opts.get("dir", "")), opts.get("file", ""), opts.get("ext", ""), save)
    else:
        default = os.path.join(opts.get("dir", ""), opts.get("file", "") + (
            "." + opts["ext"] if opts.get("ext") and opts.get("file") else ""))
        p = rt.host.ask_input(title, default)
    if not p:
        raise Cancelled("no file selected")
    return p


@macro("docgen", "Forms", '{#docgen -header "Select paragraphs" -folder "Templates/Letters" -save "C:\\out.txt" -open}',
       "Document Generator: pick phrases of a folder (in order) and output them together; "
       "optionally save the document to a file.")
def _docgen(rt, args, opts):
    if rt.store is None:
        raise MacroError("document generator needs the phrase store")
    fid = _folder_id(rt.store, opts.get("folder", ""))
    phrases = rt.store.phrases(fid) if fid is not None else []
    if not phrases:
        raise MacroError(f"no phrases in folder {opts.get('folder', '')!r}")
    names = [p.description for p in phrases]
    picked = rt.host.choose(opts.get("header", "Select phrases"), names, multi=True)
    if not picked:
        raise Cancelled("nothing selected")
    from phraseforge.macros.commands import _insert
    from phraseforge.macros.engine import actions_to_text
    parts = [actions_to_text(_as_list(_insert(rt, [str(p.id)], {})))
             for p in phrases if p.description in picked]
    doc = _esc(opts.get("sep", "\\n")).join(parts)
    if opts.get("save"):
        _outputfile(rt, [opts["save"], doc], {"open": opts.get("open", "")})
        return None
    return doc


def _as_list(res):
    if res is None:
        return []
    return res if isinstance(res, list) else [res]


# ====================================================================== phrases
def _folder_id(store, path: str):
    """Folder id from a path like 'A/B' (None = top level / not found -> None)."""
    parent = None
    parts = [p.strip() for p in re.split(r"[\\/]", path or "") if p.strip()]
    if not parts:
        return None
    for name in parts:
        f = next((f for f in store.folders(parent) if f.name.lower() == name.lower()), None)
        if f is None:
            return None
        parent = f.id
    return parent


def _resolve_insert(rt, args, opts) -> str:
    """Phrase key for {#insert}: description, -autotext abbreviation, or a pick from -folder."""
    key = _arg(args, 0)
    store = rt.store
    if opts.get("autotext") and store is not None:
        from phraseforge.models import TriggerKind
        t = next((t for t in store.triggers(TriggerKind.AUTOTEXT) if t.value == opts["autotext"]), None)
        if t is None:
            raise MacroError(f"no phrase with autotext {opts['autotext']!r}")
        return str(t.phrase_id)
    if opts.get("folder") is not None and store is not None and "folder" in opts:
        cache_key = "_insert_" + opts["folder"] + opts.get("pick", "")
        if _flag(opts, "same") and cache_key in rt.locals:
            return rt.locals[cache_key]
        fid = _folder_id(store, opts["folder"])
        phrases = store.phrases(fid) if fid is not None else []
        if not phrases:
            raise MacroError(f"no phrases in folder {opts['folder']!r}")
        pick = opts.get("pick", "manual").lower()
        if pick == "random":
            p = rt.rng.choice(phrases)
        elif pick.isdigit():
            n = int(pick)
            if not 1 <= n <= len(phrases):
                raise MacroError(f"folder has only {len(phrases)} phrases")
            p = phrases[n - 1]
        else:
            chosen = rt.host.choose(opts.get("prompt", "Select a phrase"), [x.description for x in phrases])
            if not chosen:
                raise Cancelled("no phrase chosen")
            p = next(x for x in phrases if x.description == chosen[0])
        rt.locals[cache_key] = str(p.id)
        return str(p.id)
    return key


def _insert_ex(rt, args, opts):
    from phraseforge.macros.commands import _insert
    key = _resolve_insert(rt, args, opts)
    return _insert(rt, [key], {})


register("insert", "Phrases", '{#insert "Phrase description" -autotext abbr -folder "A/B" -pick manual|random|N -same}',
         "Insert another phrase (its macros run too): by description, by its autotext, or picked from a folder.",
         '{#insert "Phrase description"}', fn=_insert_ex)


@macro("setphrase", "Phrases", '{#setphrase "Description" "content" -target "Existing phrase" -folder "A/B"}',
       "Create a phrase, or replace the content of -target (no output).")
def _setphrase(rt, args, opts):
    store = rt.store
    if store is None:
        raise MacroError("setting phrase content needs the phrase store")
    desc, content = _arg(args, 0), _arg(args, 1, opts.get("content", ""))
    target = opts.get("target")
    p = store.find_phrase(target) if target else (store.find_phrase(desc) if desc else None)
    if p is not None:
        p.content = content
        if desc:
            p.description = desc
        store.update_phrase(p)
        return None
    from phraseforge.models import Phrase
    fid = None
    if opts.get("folder"):
        from phraseforge.io_formats import ensure_folder_path
        fid = ensure_folder_path(store, opts["folder"])
    store.add_phrase(Phrase(desc or "New phrase", content, folder_id=fid))
    return None


# ====================================================================== automation
@macro("focus", "System", '{#focus -process notepad.exe -title "Untitled" -state normal|max|min|none -timeout 5}',
       "Bring an application window to the front.")
def _focus(rt, args, opts):
    fn = _host(rt, "focus_window")
    process, title = opts.get("process", _arg(args, 0)), opts.get("title", "")
    if fn is not None:
        ok = fn(process, title, opts.get("state", "none"))
    else:
        ok = rt.host.wait_for_window(title or process, float(opts.get("timeout", "5")))
    if not ok and _flag(opts, "abort"):
        raise Cancelled("window not found")
    return None


@macro("web", "System", '{#web "https://example.com" -browser default|chrome|edge|firefox}',
       "Open a web page.")
def _web(rt, args, opts):
    url = _arg(args, 0)
    if url and not re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
        url = "https://" + url
    browser = opts.get("browser", "default").lower()
    exe = {"chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe", "brave": "brave.exe"}.get(browser)
    if exe:
        rt.host.run_program(exe, url)
    else:
        rt.host.open_target(url)
    return None


# ====================================================================== external data
@macro("document", "Files & data", '{#document "C:\\letter.docx"}',
       "Insert the text of an external document (.docx, .rtf, .html, .txt, ...).")
def _document(rt, args, opts):
    path = os.path.expandvars(_arg(args, 0))
    p = Path(path)
    if not p.is_file():
        raise MacroError(f"file not found: {path}")
    ext = p.suffix.lower()
    if ext in (".docx", ".docm", ".dotx"):
        import zipfile
        from xml.etree import ElementTree as ET
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(p) as z:
            root = ET.fromstring(z.read("word/document.xml"))
        paras = []
        for para in root.iter(ns + "p"):
            paras.append("".join(t.text or "" for t in para.iter(ns + "t")))
        return "\n".join(paras)
    raw = p.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    if ext == ".rtf":
        text = re.sub(r"\\par[d]?", "\n", text)
        text = re.sub(r"\{\\\*[^{}]*\}|\\[a-z]+-?\d* ?|[{}]", "", text)
        return text.strip()
    if ext in (".htm", ".html"):
        from phraseforge.macros.engine import html_to_text
        return html_to_text(text)
    return text


def _mail_ex(rt, args, opts):
    """{#mail} with -attach and -send via Outlook when available; mailto otherwise."""
    attach = opts.get("attach", "")
    method = rt.setting("mail.method", "mailto")   # Settings > Expert Options > Email Delivery Method
    if attach or _flag(opts, "send") or _flag(opts, "outlook") or method in ("outlook", "mapi"):
        try:
            import win32com.client  # type: ignore
            app = win32com.client.Dispatch("Outlook.Application")
            m = app.CreateItem(0)
            m.To = opts.get("to", _arg(args, 0))
            m.CC, m.BCC = opts.get("cc", ""), opts.get("bcc", "")
            m.Subject, m.Body = opts.get("subject", ""), opts.get("body", "")
            for a in [x.strip() for x in attach.split(";") if x.strip()]:
                m.Attachments.Add(os.path.expandvars(a))
            m.Send() if _flag(opts, "send") else m.Display()
            return None
        except Exception:
            if attach:
                raise MacroError("attachments need Microsoft Outlook")
    from phraseforge.macros.commands import _mail
    return _mail(rt, args, opts)


register("mail", "Internet", '{#mail -to a@b.com -cc c@d.com -bcc e@f.com -subject "Hi" -body "Text" '
         '-attach "C:\\file.pdf" -send}',
         "Create an e-mail. -attach and -send use Outlook; otherwise the default mail app opens.",
         '{#mail -to "" -subject ""}', fn=_mail_ex)


@macro("csv", "Files & data", '{#csv "C:\\data.csv" -fromrow 1 -torow 1 -fromcol 1 -tocol 1 -colsep ", " '
       '-rowsep "\\n" -delimiter ,}', "Read a range of cells from a CSV file (1-based rows/columns).")
def _csv(rt, args, opts):
    path = os.path.expandvars(_arg(args, 0))
    if not Path(path).is_file():
        raise MacroError(f"file not found: {path}")
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    delim = opts.get("delimiter") or ""
    if not delim:
        try:
            delim = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
    rows = list(csv.reader(io.StringIO(text), delimiter=_esc(delim)))
    r1, r2 = int(opts.get("fromrow", "1")), int(opts.get("torow", opts.get("fromrow", "1")))
    c1, c2 = int(opts.get("fromcol", "1")), int(opts.get("tocol", opts.get("fromcol", "1")))
    out = []
    for row in rows[r1 - 1:r2]:
        out.append(_esc(opts.get("colsep", ", ")).join(row[c1 - 1:c2]))
    return _esc(opts.get("rowsep", "\\n")).join(out)


def _find_in_sheet(args, opts, want: str) -> str:
    import openpyxl
    from openpyxl.utils import get_column_letter
    from phraseforge.macros.commands import _sheet
    needle = _arg(args, 1).strip().lower()
    wb = openpyxl.load_workbook(os.path.expandvars(_arg(args, 0)), read_only=True, data_only=True)
    try:
        ws = _sheet(wb, opts.get("sheet", ""))
        for r, row in enumerate(ws.iter_rows(values_only=True), start=1):
            for c, v in enumerate(row, start=1):
                if v is not None and str(v).strip().lower() == needle:
                    if want == "col":
                        return get_column_letter(c) if _flag(opts, "letter") else str(c)
                    return str(r)
    finally:
        wb.close()
    return "0"


@macro("xlsfindcol", "Files & data", '{#xlsfindcol "C:\\data.xlsx" "search text" -sheet 1 -letter}',
       "Number (or -letter) of the first column containing a cell equal to the search text (0 = not found).")
def _xlsfindcol(rt, args, opts):
    return _find_in_sheet(args, opts, "col")


@macro("xlsfindrow", "Files & data", '{#xlsfindrow "C:\\data.xlsx" "search text" -sheet 1}',
       "Number of the first row containing a cell equal to the search text (0 = not found).")
def _xlsfindrow(rt, args, opts):
    return _find_in_sheet(args, opts, "row")


@macro("dbquery", "Files & data",
       '{#dbquery "SELECT name FROM t" -engine sqlite|odbc -database "C:\\db.sqlite" -connection "DSN=..." '
       '-sep ", " -rowsep "\\n"}',
       "Query a database: SQLite file (read-only) or any ODBC connection string (needs pyodbc).")
def _dbquery(rt, args, opts):
    engine = opts.get("engine", "sqlite").lower()
    query = _arg(args, 0)
    sep, rsep = _esc(opts.get("sep", ", ")), _esc(opts.get("rowsep", "\\n"))
    if engine == "sqlite":
        from phraseforge.macros.commands import _sql
        return _sql(rt, [opts.get("database", ""), query], {"sep": opts.get("sep", ", "),
                                                               "rowsep": opts.get("rowsep", "\\n")})
    try:
        import pyodbc  # type: ignore
    except ImportError as e:
        raise MacroError("ODBC queries need the pyodbc package") from e
    con = pyodbc.connect(opts.get("connection") or _odbc_string(engine, opts), timeout=10)
    try:
        rows = con.cursor().execute(query).fetchmany(int(opts.get("limit", "1000")))
    finally:
        con.close()
    return rsep.join(sep.join("" if v is None else str(v) for v in r) for r in rows)


def _odbc_string(engine: str, opts) -> str:
    driver = {"mssql": "ODBC Driver 17 for SQL Server", "mysql": "MySQL ODBC 8.0 Unicode Driver",
              "postgresql": "PostgreSQL Unicode", "access": "Microsoft Access Driver (*.mdb, *.accdb)"}.get(engine, engine)
    parts = [f"DRIVER={{{driver}}}"]
    if opts.get("server"):
        parts.append(f"SERVER={opts['server']}" + (f",{opts['port']}" if opts.get("port") else ""))
    if opts.get("database"):
        parts.append(("DBQ=" if engine == "access" else "DATABASE=") + opts["database"])
    if _flag(opts, "osauth"):
        parts.append("Trusted_Connection=yes")
    else:
        if opts.get("user"):
            parts.append(f"UID={opts['user']}")
        if opts.get("password"):
            parts.append(f"PWD={opts['password']}")
    return ";".join(parts)


# ---------------------------------------------------------------- Outlook / ActiveDirectory
OUTLOOK_FIELDS = ("title", "firstname", "lastname", "senderemail", "recipientemail", "subject", "body", "gender")


@macro("outlook", "Files & data", "{#outlook subject}",
       "Field of the e-mail currently open/selected in Outlook: " + ", ".join(OUTLOOK_FIELDS) +
       ". Outputs nothing if Outlook is not available.")
def _outlook(rt, args, opts):
    field = _arg(args, 0, "subject").lower()
    if field not in OUTLOOK_FIELDS:
        raise MacroError(f"unknown Outlook field {field!r}")
    try:
        import win32com.client  # type: ignore
        app = win32com.client.GetActiveObject("Outlook.Application")
        insp = app.ActiveInspector()
        item = insp.CurrentItem if insp is not None else None
        if item is None:
            sel = app.ActiveExplorer().Selection
            item = sel.Item(1) if sel.Count else None
        if item is None:
            return ""
    except Exception:
        return ""      # Outlook not running / not installed
    try:
        sender = str(getattr(item, "SenderName", "") or "")
        first, _, last = sender.partition(" ")
        if field == "subject":
            return str(item.Subject or "")
        if field == "body":
            return str(item.Body or "")
        if field == "senderemail":
            return str(getattr(item, "SenderEmailAddress", "") or "")
        if field == "recipientemail":
            r = item.Recipients
            return str(r.Item(1).Address) if r.Count else ""
        if field == "firstname":
            return first
        if field == "lastname":
            return last
        if field in ("title", "gender"):
            return ""   # not exposed by the Outlook object model for plain mail items
    except Exception:
        return ""
    return ""


AD_FIELDS = {"name": "displayName", "email": "mail", "nickname": "sAMAccountName",
             "telephone": "telephoneNumber", "street": "streetAddress", "zip": "postalCode", "city": "l",
             "company": "company", "department": "department", "title": "title", "firstname": "givenName",
             "lastname": "sn", "mobile": "mobile", "country": "co", "office": "physicalDeliveryOfficeName"}


@macro("ad", "Files & data", "{#ad email -user current}",
       "ActiveDirectory attribute of the current user (name, email, nickname, telephone, street, zip, city, ... "
       "or any LDAP attribute). Outputs nothing outside a domain.")
def _ad(rt, args, opts):
    field = _arg(args, 0, "name")
    attr = AD_FIELDS.get(field.lower(), field)
    try:
        import win32com.client  # type: ignore
        info = win32com.client.Dispatch("ADSystemInfo")
        user = win32com.client.GetObject("LDAP://" + info.UserName)
        v = user.Get(attr)
        return "" if v is None else str(v)
    except Exception:
        return ""


# ====================================================================== forms (extra field types)
def _register_field_aliases():
    from phraseforge.macros.commands import _field

    def separator(rt, args, opts):
        return _field(rt, "label", [opts.get("name", f"sep{len(rt.field_specs) + 1}")], {"label": "—" * 30})

    register("formseparator", "Forms", "{#formseparator}", "Form field: horizontal separator line.",
             "{#formseparator}", fn=separator)

    def slider(rt, args, opts):
        return _field(rt, "number", args, opts)

    register("formslider", "Forms", '{#formslider name -label "Label" -min 0 -max 100 -default 50}',
             "Form field: numeric slider (shown as a number box where sliders are not supported).",
             '{#formslider name -label "Label" -min 0 -max 100}', fn=slider)

    def phrases(rt, args, opts):
        store = rt.store
        fid = _folder_id(store, opts.get("folder", "")) if store is not None else None
        items = [p.description for p in store.phrases(fid)] if (store is not None and fid is not None) else []
        name = _arg(args, 0, opts.get("name", f"field{len(rt.field_specs) + 1}"))
        res = _field(rt, "combo", [name], {**opts, "options": "|".join(items), "sep": "|"})
        rt.field_specs[name] = {**rt.field_specs.get(name, {}), "phrases": "1"}
        if res is None:          # inside {#form}: value read later via {#formvalue}
            return None
        return _insert_ex(rt, [res], {}) if res else ""

    register("formphrases", "Forms", '{#formphrases name -label "Label" -folder "A/B"}',
             "Form field: drop-down of the phrases in a folder; outputs the chosen phrase (macros run).",
             '{#formphrases choice -label "Select" -folder "Templates"}', fn=phrases)

    def enum(rt, args, opts):
        """Checklist; outputs the checked items joined like "a, b and c"."""
        name = _arg(args, 0, opts.get("name", f"enum{len(rt.field_specs) + 1}"))
        items = [x for x in opts.get("options", "").split(opts.get("sep", "|")) if x]
        sep, last = _esc(opts.get("delim", ", ")), _esc(opts.get("last", " and "))
        from phraseforge.host import FormField
        fields = [FormField("checkbox", f"{name}__{i}", label=it, default=False) for i, it in enumerate(items)]
        if opts.get("label"):
            fields.insert(0, FormField("label", f"{name}__label", label=opts["label"]))
        if rt.collecting is not None:
            rt.collecting.extend(fields)
            rt.field_specs[name] = {**opts, "enum_items": "|".join(items)}
            return None
        values = rt.host.show_form(opts.get("title", opts.get("label", name)), fields)
        chosen = [it for i, it in enumerate(items) if _truthy(values.get(f"{name}__{i}"))]
        out = chosen[0] if len(chosen) == 1 else (sep.join(chosen[:-1]) + last + chosen[-1]) if chosen else ""
        rt.form_values[name] = out
        return out

    register("formenum", "Forms", '{#formenum name -label "Label" -options "a|b|c" -delim ", " -last " and "}',
             "Form field: enumeration group (checklist); outputs checked items joined with the delimiters.",
             '{#formenum items -label "Include" -options "a|b|c"}', fn=enum)


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


_register_field_aliases()


# ---------------------------------------------------------------- Microsoft OneNote
@macro("onenote", "External data", '{#onenote "Notebook/Section/Page" -title -ocr}',
       "Insert the text of a OneNote page (desktop OneNote, official API). -title adds the page title; "
       "-ocr adds text OneNote recognised in images.")
def _onenote(rt, args, opts):
    ref = _arg(args, 0)
    if not ref:
        raise MacroError("onenote: page path missing")
    host = rt.host
    fn = getattr(host, "onenote_page_text", None)
    setting = getattr(host, "setting", lambda k, d="": d)
    include_ocr = _flag(opts, "ocr") or setting("onenote.include_ocr", "0") == "1"
    if fn is not None:
        return fn(ref, include_title=_flag(opts, "title"), include_ocr=include_ocr)
    from phraseforge.onenote import OneNote, DEFAULT_EXE
    return OneNote(setting("onenote.exe", DEFAULT_EXE) or DEFAULT_EXE).page_text(
        ref, include_title=_flag(opts, "title"), include_ocr=include_ocr)


# ---------------------------------------------------------------- Microsoft Sticky Notes
@macro("stickynote", "External data", '{#stickynote "first line or search word" -all -sep "\\n---\\n"}',
       "Insert the text of a Sticky Notes note (matched by its first line, else the newest note "
       "containing the words). -all inserts every note. Reads a copy of your notes file; Sticky Notes "
       "itself is never changed.")
def _stickynote(rt, args, opts):
    from phraseforge import stickynotes
    notes = stickynotes.read_notes()
    if not notes:
        raise MacroError("stickynote: no Sticky Notes found")
    if _flag(opts, "all"):
        sep = opts.get("sep", "\n\n---\n\n").replace("\\n", "\n")
        return sep.join(n.text for n in notes)
    note = stickynotes.find(notes, _arg(args, 0))
    if note is None:
        raise MacroError(f"stickynote: no note matches {_arg(args, 0)!r}")
    return note.text
