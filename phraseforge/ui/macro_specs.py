"""Every macro dialog, declared with macro_dialog_kit.

Each spec mirrors one PhraseExpress dialog (reference/phraseexpress/11_*, 13_*):
same title, field order and labels, producing PhraseForge macro syntax.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QRadioButton, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
)

from phraseforge.ui.iconset import icon
from phraseforge.ui.macro_dialog_kit import (
    Button, Check, Column, Combo, Custom, FilePath, Group, Line, LinkLabel, ListPick, MacroSpec, Memo,
    PickPhrase, Preview, Radio, Row, Spin, Text, call, get_store, pick_phrase_or_folder, preview_macro, q,
)

RIGHT_CLICK = " (Right-click to insert macro)"
SPECS: dict[str, MacroSpec] = {}


def spec(s: MacroSpec) -> MacroSpec:
    SPECS[s.kind] = s
    return s


def gen(cmd: str, args=(), opts=(), flags=(), extra=None):
    """Generic build/parse pair. args: value keys in order; opts: (option, key) pairs;
    flags: (option, key) pairs for checkboxes."""
    def build(v):
        o = {name: v.get(key) for name, key in opts}
        o.update({name: bool(v.get(key)) for name, key in flags})
        if extra:
            o.update(extra(v))
        return call(cmd, *[v.get(k) for k in args], **o)

    def parse(a, o):
        v = {k: a[i] for i, k in enumerate(args) if i < len(a)}
        for name, key in opts:
            if name in o:
                v[key] = o[name]
        for name, key in flags:
            v[key] = name in o and o[name] not in ("0", "false")
        return v
    return build, parse


def text_spec(kind, title, cmd, label="Text" + RIGHT_CLICK, menu_text="", description=""):
    b, p = gen(cmd, args=("text",))
    return spec(MacroSpec(kind, title, b, [Memo("text", label, height=150)], commands=(cmd,), parse=p,
                          menu_text=menu_text, description=description))


# ============================================================================ helpers
LOCALES = [("", ""), ("English", "en"), ("Arabic", "ar"), ("German", "de")]
DATE_PRESETS = ["dddd, d. MMMM yyyy HH:mm:ss", "dd.MM.yyyy", "MM/dd/yyyy", "dddd, yyyy-MM-dd",
                "d. MMMM yyyy", "d. MMMM", "MMMM yyyy", "yyyy", "yy", "MMMM", "MM", "M", "dddd", "dd", "d",
                "DDD", "HH:mm:ss", "HH:mm", "hh:mm tt", "yyyy-MM-dd", "yyyy-MM-dd HH:mm"]
PRESET_NOTES = {"yy": " (Year)", "MM": " (Month [01-12])", "M": " (Month [1-12])", "dd": " (Day of Month [01-31])",
                "d": " (Day of Month [1-31])", "DDD": " (Day of the year)"}
WEEKDAYS = [("Monday", "mon"), ("Tuesday", "tue"), ("Wednesday", "wed"), ("Thursday", "thu"),
            ("Friday", "fri"), ("Saturday", "sat"), ("Sunday", "sun")]
ROUND_STEPS = [(f"{n} minutes" if n != 60 else "1 hour", str(n)) for n in (1, 5, 10, 15, 20, 30, 60)]
SYNTAX = [("No validation", ""), ("Number", "number"), ("Integer", "integer"), ("Email address", "email"),
          ("Date", "date"), ("Time", "time"), ("Phone number", "phone"), ("Web address (URL)", "url"),
          ("Not empty", "notempty"), ("Letters only", "letters")]


def _preset_options():
    from phraseforge.macros.datetimes import format_dt
    now = datetime.now()
    out = []
    for f in DATE_PRESETS:
        try:
            sample = format_dt(now, f, "en")
        except Exception:
            sample = f
        out.append((sample + PRESET_NOTES.get(f, ""), f))
    return out


def slug(label: str, fallback: str = "field") -> str:
    s = re.sub(r"\W+", "_", (label or "").strip().lower(), flags=re.UNICODE).strip("_")
    return s[:30] or fallback


def lines_to_list(text: str) -> list[str]:
    return [x.strip() for x in (text or "").splitlines() if x.strip()]


# ============================================================================ Date/Time
def _date_offset(v) -> str:
    parts = []
    if int(v.get("shift_date") or 0):
        unit = {"days": "d", "weeks": "w", "months": "m", "years": "y", "workdays": "wd"}[v.get("shift_date_unit") or "days"]
        parts.append(f"{int(v['shift_date']):+d}{unit}")
    if int(v.get("shift_time") or 0):
        unit = {"hours": "h", "minutes": "min", "seconds": "s"}[v.get("shift_time_unit") or "hours"]
        parts.append(f"{int(v['shift_time']):+d}{unit}")
    return " ".join(parts)


def build_date_time(v):
    o = {"format": v.get("format") or "", "offset": _date_offset(v), "lang": v.get("locale") or ""}
    if int(v.get("shift_weekday_n") or 0):
        o["weekday"] = f"{v.get('shift_weekday') or 'mon'}:{int(v['shift_weekday_n'])}"
    if v.get("round"):
        o["round"] = v.get("round_to") or "15"
        o["roundup"] = bool(v.get("round_up"))
    if v.get("value"):
        return call("datecalc", v["value"], **{k: x for k, x in o.items() if k in ("format", "offset", "lang")})
    return call("date", **o)


def parse_date_time(a, o):
    v = {"format": o.get("format", ""), "locale": o.get("lang", ""), "value": a[0] if a else ""}
    for part in (o.get("offset") or "").split():
        m = re.fullmatch(r"([+-]\d+)(wd|min|mo|[dwmyhs])", part)
        if not m:
            continue
        n, u = int(m.group(1)), m.group(2)
        if u in ("h", "min", "s"):
            v["shift_time"], v["shift_time_unit"] = n, {"h": "hours", "min": "minutes", "s": "seconds"}[u]
        else:
            v["shift_date"], v["shift_date_unit"] = n, {"d": "days", "w": "weeks", "m": "months", "mo": "months",
                                                       "y": "years", "wd": "workdays"}[u]
    if o.get("weekday"):
        d, _, n = o["weekday"].partition(":")
        v["shift_weekday"], v["shift_weekday_n"] = d, int(n or 1)
    if o.get("round"):
        v["round"], v["round_to"], v["round_up"] = True, o["round"], "roundup" in o
    return v


def _preset_hook(dlg, value):
    if value:
        dlg.setters["format"](value)


spec(MacroSpec(
    "date_time", "Date/Time", build_date_time, commands=("date", "time", "datetime"), parse=parse_date_time,
    description="This macro inserts a customizable time and date stamp. You can also configure a time shift "
                "from the current time.", width=596, shortcut="Ctrl+D", hooks={"preset": _preset_hook},
    fields=[Row(fields=[
        Column(fields=[ListPick("preset", "Presets:", options=_preset_options(), height=300, width=160)]),
        Column(stretch=1, fields=[
            Row(fields=[Line("format", "Format:"), Combo("locale", "Locale:", options=LOCALES, width=120)]),
            Line("value", "Value:", pencil=True, tip="Optional fixed date instead of now (e.g. 2026-12-31)"),
            Group(title="Shift:", fields=[
                Row(fields=[Text(text="Shift date by"), Spin("shift_date", minimum=-99999, maximum=99999, width=60),
                            Combo("shift_date_unit", options=["days", "weeks", "months", "years", "workdays"], width=110)]),
                Row(fields=[Text(text="Shift time by"), Spin("shift_time", minimum=-99999, maximum=99999, width=60),
                            Combo("shift_time_unit", options=["hours", "minutes", "seconds"], width=110)]),
                Row(fields=[Text(text="Shift date by"), Spin("shift_weekday_n", minimum=0, maximum=52, width=60),
                            Combo("shift_weekday", options=WEEKDAYS, width=110)]),
            ]),
            Group(title="Round time", fields=[
                Row(fields=[Check("round", "Round to"), Combo("round_to", options=ROUND_STEPS, default="15", width=130)]),
                Check("round_up", "Round up only", enabled_if=("round", True)),
            ]),
            Preview(),
        ]),
    ])]))


def build_date_calc(v):
    return call("datecalc", v.get("date1") or "today", diff=v.get("date2") or "today", unit=v.get("unit") or "years")


spec(MacroSpec("date_calc", "Date Calculation", build_date_calc, commands=("datecalc",),
               parse=lambda a, o: {"date1": "" if (a and a[0] == "today") else (a[0] if a else ""),
                                   "date2": "" if o.get("diff") == "today" else o.get("diff", ""),
                                   "unit": o.get("unit", "years")},
               fields=[Line("date1", "Date 1 (leave empty for current date):"),
                       Line("date2", "Date 2 (leave empty for current date):"),
                       Combo("unit", "Calculate number of...:", options=[
                           ("Years", "years"), ("Months", "months"), ("Weeks", "weeks"), ("Days", "days"),
                           ("Workdays", "workdays"), ("Hours", "hours"), ("Minutes", "minutes"), ("Seconds", "seconds")])]))


def build_time_calc(v):
    o = {"diff": v.get("time2") or "now", "unit": v.get("output") or "custom"}
    if (v.get("output") or "custom") == "custom":
        o["format"] = v.get("format") or "HH:mm"
    if v.get("round"):
        o["round"], o["roundup"] = v.get("round_to") or "15", bool(v.get("round_up"))
    return call("timecalc", v.get("time1") or "now", **o)


spec(MacroSpec("time_calc", "Time Calculation", build_time_calc, commands=("timecalc",), width=400,
               parse=lambda a, o: {"time1": "" if (a and a[0] == "now") else (a[0] if a else ""),
                                   "time2": "" if o.get("diff") == "now" else o.get("diff", ""),
                                   "output": o.get("unit", "custom"), "format": o.get("format", ""),
                                   "round": "round" in o, "round_to": o.get("round", "15"), "round_up": "roundup" in o},
               fields=[Line("time1", "Time 1 (leave empty for current time):"),
                       Line("time2", "Time 2 (leave empty for current time):"),
                       Combo("output", "Output:", options=[("Custom", "custom"), ("Hours", "hours"),
                                                           ("Minutes", "minutes"), ("Seconds", "seconds")]),
                       Line("format", "Format:", placeholder="HH:mm", enabled_if=("output", "custom")),
                       Group(title="Round time", fields=[
                           Row(fields=[Check("round", "Round to"), Combo("round_to", options=ROUND_STEPS, default="15", width=130)]),
                           Check("round_up", "Round up only", enabled_if=("round", True))])]))


# ============================================================================ User input
def build_manual_input(v):
    return call("input", v.get("header") or "Input", default=v.get("default") or "",
                multiline=not v.get("single"), syntax=v.get("syntax") or "")


spec(MacroSpec("manual_input", "Manual text input", build_manual_input, commands=("input", "inputmemo"),
               parse=lambda a, o: {"header": a[0] if a else "", "default": o.get("default", ""),
                                   "single": "multiline" not in o, "syntax": o.get("syntax", "")},
               description="Inserts manual text input with an optional default text.", width=490, shortcut="Ctrl+M",
               fields=[Line("header", "Header:"), Memo("default", "Default text" + RIGHT_CLICK, height=44),
                       Check("single", "Single line"), Combo("syntax", "Syntax:", options=SYNTAX, width=226)]))

FORM_TYPES = [("Single-line input", "edit"), ("Multi-line input", "memo"), ("Drop-down list", "combo"),
              ("Radio buttons", "radio"), ("Checkbox", "checkbox"), ("Date", "date"), ("Number", "number")]


def _form_type_widget(dlg):
    btn = QToolButton()
    btn.setPopupMode(QToolButton.InstantPopup)
    btn.setMinimumWidth(270)
    btn.setStyleSheet("QToolButton { background:#e1e1e1; border:1px solid #c0c0c0; padding:3px; }")
    from PySide6.QtWidgets import QMenu
    m = QMenu(btn)
    state = {"v": "edit"}

    def setv(val):
        state["v"] = val
        btn.setText(dict((v, t) for t, v in FORM_TYPES).get(val, "Single-line input"))
        dlg._refresh() if hasattr(dlg, "ok_btn") else None
    for t, val in FORM_TYPES:
        m.addAction(t, lambda val=val: setv(val))
    btn.setMenu(m)
    setv("edit")
    return btn, lambda: state["v"], setv


def build_form_input(v):
    kind = v.get("type") or "edit"
    name = slug(v.get("label"), "input")
    o = {"label": v.get("label") or "", "default": v.get("default") or "", "syntax": v.get("syntax") or "",
         "remember": bool(v.get("remember"))}
    if kind in ("combo", "radio"):
        o["options"] = "|".join(lines_to_list(v.get("options")))
        o["sep"] = "|" if o["options"] else ""
    if kind == "checkbox":
        o = {"label": o["label"], "checked": str(v.get("default")).lower() in ("1", "yes", "true", "x")}
    return call("form" + kind, name, **o)


spec(MacroSpec("form_input", "Form input", build_form_input, layout="form", width=776, name="Single-line input",
               commands=("formedit", "formmemo", "formcombo", "formradio", "formcheckbox", "formdate", "formnumber"),
               parse=lambda a, o: {"label": o.get("label", ""), "default": o.get("default", ""),
                                   "syntax": o.get("syntax", ""), "options": "\n".join(
                                       x for x in o.get("options", "").split(o.get("sep", ",")) if x)},
               description="Form input control. Select type and configure the control.",
               fields=[Custom("type", "Type", factory=_form_type_widget), Line("label", "Label", width=270),
                       Combo("syntax", "Syntax", options=SYNTAX, width=270), Line("default", "Default value", pencil=True),
                       Memo("options", "Options (one per line)", height=60,
                            visible_if=("type", ("combo", "radio"))),
                       Check("remember", "Last user input/selection")]))


def build_docgen(v):
    o = {"header": v.get("header") or "", "folder": v.get("folder") or "", "templates": v.get("templates") or "",
         "default": v.get("default_template") or ""}
    if v.get("save"):
        o["save"] = v.get("save_path") or ""
        if v.get("use_template"):
            o["template"] = v.get("template_path") or ""
    return call("docgen", **o)


spec(MacroSpec("document_generator", "Document Generator", build_docgen, commands=("docgen",), process_output=False,
               width=480, parse=lambda a, o: {"header": o.get("header", ""), "folder": o.get("folder", ""),
                                             "templates": o.get("templates", ""),
                                             "default_template": o.get("default", ""), "save": "save" in o,
                                             "save_path": o.get("save", ""), "use_template": "template" in o,
                                             "template_path": o.get("template", "")},
               fields=[Line("header", "Header:", width=420), PickPhrase("folder", "Show phrases of folder:", kind="folder"),
                       PickPhrase("templates", "Save templates in folder:", kind="folder"),
                       PickPhrase("default_template", "Default template:", kind="phrase"),
                       Check("save", "Save output to file"),
                       FilePath("save_path", mode="save", enabled_if=("save", True)),
                       Check("use_template", "Use template", enabled_if=("save", True)),
                       FilePath("template_path", enabled_if=("use_template", True))]))


def _file_dialog_spec(kind, title, cmd):
    b, p = gen(cmd, opts=(("title", "title"), ("ext", "ext"), ("file", "file"), ("dir", "dir")))
    spec(MacroSpec(kind, title, b, commands=(cmd,), parse=p,
                   fields=[Line("title", "Title:"), Line("ext", "Default extension:"),
                           Line("file", "Default file name (without file extension):"),
                           FilePath("dir", "Default directory:", mode="dir")]))


_file_dialog_spec("file_select", "File selection dialog", "fileselect")
_file_dialog_spec("file_save", "File save dialog", "filesave")


# ---------------------------------------------------------------- Form submenu
def build_form_appearance(v):
    o = {"title": v.get("title") or "", "width": v.get("width") or "", "height": v.get("height") or "",
         "fontsize": v.get("fontsize") or "", "preview": "" if v.get("preview") == "icon" else v.get("preview")}
    o = {k: (x if str(x) != "0" else "") for k, x in o.items()}
    return call("form", **o) + "\n\n{#endform}"


spec(MacroSpec("form_appearance", "Form appearance", build_form_appearance, commands=("form",), process_output=False,
               parse=lambda a, o: {"title": o.get("title", ""), "width": o.get("width", 0), "height": o.get("height", 0),
                                   "fontsize": o.get("fontsize", 0), "preview": o.get("preview", "icon")},
               fields=[Line("title", "Form window title:"),
                       Spin("width", "Width (in pixels):", suffix="pixels (0 for default)", width=60),
                       Spin("height", "Height (in pixels):", suffix="pixels (0 for default)", width=60),
                       Spin("fontsize", "Font size:", suffix="pixels (0 for default)", width=60),
                       Radio("preview", options=[("Enable output preview pane", "pane"),
                                                 ("Show output preview icon", "icon"),
                                                 ("No output preview", "none")], default="icon")]))

spec(MacroSpec("text_label", "Text label", lambda v: call("formlabel", slug(v.get("label"), "label"),
                                                         label=v.get("label"), link=v.get("link"), hint=v.get("hint")),
               commands=("formlabel",), process_output=False, width=488,
               parse=lambda a, o: {"label": o.get("label", ""), "link": o.get("link", ""), "hint": o.get("hint", "")},
               fields=[Line("label", "Label:", width=250), Line("link", "Link:"),
                       Line("hint", "Hint text (appears on mouse hover):")]))

spec(MacroSpec("separator", "Separator", lambda v: "{#formseparator}", commands=("formseparator",), direct=True))

spec(MacroSpec("enum_group", "Enumeration group",
               lambda v: call("formenum", slug(v.get("label"), "items"), label=v.get("label"),
                              options="|".join(lines_to_list(v.get("elements"))), sep="|",
                              delim=v.get("delim") if v.get("delim") != ", " else "",
                              last=v.get("last") if v.get("last") != " and " else ""),
               commands=("formenum",), width=508,
               parse=lambda a, o: {"label": o.get("label", ""), "delim": o.get("delim", ", "),
                                   "last": o.get("last", " and "),
                                   "elements": "\n".join(x for x in o.get("options", "").split(o.get("sep", "|")) if x)},
               fields=[Line("label", "Label:", width=270),
                       Row(fields=[Line("delim", "Delimiter:", default=", ", width=130),
                                   Line("last", "Last delimiter:", default=" and ", width=130)]),
                       Memo("elements", "Form elements (one per line; right-click to insert macro):", height=170)]))


def build_phrases_dropdown(v):
    o = {"label": v.get("label"), "hint": v.get("hint"), "remember": bool(v.get("remember"))}
    if v.get("source") == "autotext":
        return call("formphrases", slug(v.get("label"), "phrase"), autotext=v.get("autotext"), **o)
    return call("formphrases", slug(v.get("label"), "phrase"), folder=v.get("folder"), **o)


PHRASES_DROPDOWN_FIELDS = [
    Line("label", "Label:"), Line("hint", "Hint text (appears on mouse hover):"),
    Radio("source", "Folder:", options=[("Select phrase(folder)", "folder"), ("Autotext of the desired phrase:", "autotext")]),
    PickPhrase("folder", kind="folder", enabled_if=("source", "folder")),
    Line("autotext", "Autotext of the desired phrase:", width=200, enabled_if=("source", "autotext")),
    Check("remember", "Last user input/selection")]

spec(MacroSpec("phrases_dropdown", "Phrases dropdown", build_phrases_dropdown, commands=("formphrases",), width=488,
               parse=lambda a, o: {"label": o.get("label", ""), "hint": o.get("hint", ""),
                                   "source": "autotext" if "autotext" in o else "folder",
                                   "folder": o.get("folder", ""), "autotext": o.get("autotext", "")},
               fields=PHRASES_DROPDOWN_FIELDS))


def build_calendar(v):
    o = {"label": v.get("header") or "Select date", "format": v.get("format") or "", "lang": v.get("locale") or ""}
    d = v.get("default_mode") or "current"
    if d == "shift":
        unit = {"days": "d", "weeks": "w", "months": "m", "years": "y", "workdays": "wd"}[v.get("shift_unit") or "days"]
        o["shift"] = f"{int(v.get('shift_n') or 0):+d}{unit}"
    elif d == "fixed":
        o["default"] = v.get("fixed") or ""
    return call("formdate", slug(v.get("header"), "date"), **o)


def _date_editor(dlg):
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QDateEdit
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setDisplayFormat("MMMM dd-MM-yyyy")
    w.setDate(QDate.currentDate())
    w.dateChanged.connect(lambda *_: dlg._refresh() if hasattr(dlg, "ok_btn") else None)
    return (w, lambda: w.date().toString("yyyy-MM-dd"),
            lambda v: w.setDate(QDate.fromString(str(v)[:10], "yyyy-MM-dd")))


def _cal_preset_hook(dlg, value):
    if value:
        dlg.setters["format"](value)


spec(MacroSpec(
    "calendar", "Calendar", build_calendar, commands=("formdate", "datepick"), width=688,
    hooks={"preset": _cal_preset_hook},
    description="Opens a calendar date picker window. The resulting date format can be adjusted and a default "
                "value can be optionally defined.",
    parse=lambda a, o: {"header": o.get("label", ""), "format": o.get("format", ""), "locale": o.get("lang", ""),
                        "default_mode": "shift" if "shift" in o else "fixed" if o.get("default") else "current",
                        "fixed": o.get("default", "")},
    fields=[Row(fields=[
        Column(fields=[ListPick("preset", "Date Format", options=[x for x in _preset_options()
                                                               if not any(t in x[1] for t in "Hhm")], height=300)]),
        Column(stretch=1, fields=[
            Line("header", "Header:", default="Select date", width=270),
            Row(fields=[Line("format", "Format:", default="dd.MM.yyyy", width=270),
                        Combo("locale", "Locale:", options=LOCALES, width=66)]),
            Group(title="Default value", fields=[
                Radio("default_mode", options=[("Current date", "current"), ("Shift from current date", "shift"),
                                               ("Fixed date", "fixed")]),
                Row(fields=[Spin("shift_n", minimum=-9999, maximum=9999, default=1, width=60,
                                 enabled_if=("default_mode", "shift")),
                            Combo("shift_unit", options=["days", "weeks", "months", "years", "workdays"], width=110,
                                  enabled_if=("default_mode", "shift"))]),
                Custom("fixed", factory=_date_editor, enabled_if=("default_mode", "fixed")),
            ]),
            Preview(fn=lambda v: preview_macro(call("datecalc", "today" if v.get("default_mode") != "fixed"
                                                    else v.get("fixed"), format=v.get("format") or "dd.MM.yyyy",
                                                    lang=v.get("locale") or "",
                                                    offset=(f"{int(v.get('shift_n') or 0):+d}" +
                                                            {"days": "d", "weeks": "w", "months": "m", "years": "y",
                                                             "workdays": "wd"}[v.get("shift_unit") or "days"])
                                                    if v.get("default_mode") == "shift" else ""))),
        ]),
    ])]))


def _numeric(kind, title, cmd):
    def build(v):
        o = {"label": v.get("label"), "hint": v.get("hint")}
        for k in ("default", "min", "max"):
            if v.get(k) not in (None, ""):
                o[k] = v.get(k)
        return call(cmd, slug(v.get("label"), "number"), **o)
    spec(MacroSpec(kind, title, build, commands=(cmd,), width=488,
                   parse=lambda a, o: {k: o.get(k, "") for k in ("label", "hint", "default", "min", "max")},
                   fields=[Line("label", "Label:", width=250), Line("hint", "Hint text (appears on mouse hover):"),
                           Row(fields=[Line("default", "Default:", width=80), Line("min", "Min:", width=80),
                                       Line("max", "Max:", width=80)])]))


_numeric("numeric_input", "Numeric input", "formnumber")
_numeric("numeric_slider", "Numeric Slider", "formslider")


# ---------------------------------------------------------------- WYSIWYG submenu (no Name header)
spec(MacroSpec("w_input_field", "Input field",
               lambda v: call("formedit" if v.get("single") else "formmemo", "input", hint=v.get("hint"),
                              default=v.get("default"), syntax=v.get("syntax")),
               commands=(), show_name=False, process_output=False,
               fields=[Line("hint", "Hint text (appears on mouse hover):"), Memo("default", "Default value:", height=150),
                       Check("single", "Single line"), Combo("syntax", "Syntax:", options=SYNTAX, width=226)]))


def build_w_dropdown(v):
    values = lines_to_list(v.get("values")) or lines_to_list(v.get("descriptions"))
    return call("formcombo", "choice", hint=v.get("hint"), options="|".join(values), sep="|" if values else "",
                labels="|".join(lines_to_list(v.get("descriptions"))), default=v.get("default"),
                syntax=v.get("syntax"), custom=bool(v.get("custom")))


spec(MacroSpec("w_drop_down", "Drop down list", build_w_dropdown, show_name=False, process_output=False, width=459,
               fields=[Line("hint", "Hint text (appears on mouse hover):"),
                       Row(fields=[Memo("descriptions", "Description:", height=210),
                                   Memo("values", "Values:", height=210)]),
                       Line("default", "Default value:"), Combo("syntax", "Syntax:", options=SYNTAX, width=226),
                       Check("custom", "Allow custom input", default=True)]))

spec(MacroSpec("w_phrase_selection", "Phrase selection", build_phrases_dropdown, show_name=False, width=488,
               fields=PHRASES_DROPDOWN_FIELDS))

spec(MacroSpec("w_check_box", "Checkbox",
               lambda v: call("formcheckbox", slug(v.get("label"), "check"), label=v.get("label"), hint=v.get("hint"),
                              on=v.get("on"), off=v.get("off"), checked=bool(v.get("checked")),
                              required=bool(v.get("required"))),
               commands=("formcheckbox",), show_name=False, process_output=False, width=380,
               parse=lambda a, o: {"label": o.get("label", ""), "hint": o.get("hint", ""), "on": o.get("on", ""),
                                   "off": o.get("off", ""), "checked": "checked" in o, "required": "required" in o},
               fields=[Line("label", "Label:"), Line("hint", "Hint text (appears on mouse hover):"),
                       Memo("on", "Output if checked:", height=90), Memo("off", "Output if unchecked:", height=90),
                       Check("checked", "Checked by default"), Check("required", "Input required")]))

spec(MacroSpec("w_calendar", "Calendar",
               lambda v: call("formdate", "date", hint=v.get("hint"), format=v.get("format") or "dd.MM.yyyy"),
               show_name=False, process_output=False,
               fields=[Line("hint", "Hint text (appears on mouse hover):"),
                       Line("format", "Format:", default="dd.MM.yyyy")]))


# ============================================================================ External data
LANGUAGES = ["Arabic", "Chinese", "Dutch", "English", "French", "German", "Hindi", "Indonesian", "Italian",
             "Japanese", "Korean", "Malay", "Persian", "Polish", "Portuguese", "Russian", "Spanish", "Swedish",
             "Turkish", "Urdu"]

spec(MacroSpec("translate", "Translate text",
               lambda v: call("translate", v.get("text"), to=v.get("target") or "English",
                              **{"from": v.get("source") or ""}),
               commands=("translate",),
               parse=lambda a, o: {"text": a[0] if a else "", "target": o.get("to", ""), "source": o.get("from", "")},
               description="This macro sends the specified text to the configured AI provider for translation and "
                           "returns the translated text.",
               fields=[Memo("text", "Text to translate" + RIGHT_CLICK, height=56),
                       Combo("source", "Source language:", options=[("Auto-detect", "")] + LANGUAGES),
                       Combo("target", "Target language:", options=LANGUAGES, default="English", required=True),
                       Combo("glossary", "Glossary:", options=[""], enabled_if=("source", lambda v: False))]))


def _ai_settings(dlg):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout
    d = QDialog(dlg)
    d.setWindowTitle("AI settings")
    f = QFormLayout(d)
    prov = QComboBox()
    prov.addItems(["", "openai", "anthropic", "ollama", "openrouter"])
    prov.setCurrentText(dlg.extra.get("provider", ""))
    model = QLineEdit(dlg.extra.get("model", ""))
    system = QLineEdit(dlg.extra.get("system", ""))
    f.addRow("Provider (empty = default):", prov)
    f.addRow("Model (empty = default):", model)
    f.addRow("System instruction:", system)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    f.addRow(bb)
    if d.exec():
        dlg.extra.update(provider=prov.currentText(), model=model.text(), system=system.text())


def _ai_prompt_widget(dlg):
    from phraseforge.ui.macro_dialog_kit import MacroTextEdit
    dlg.extra = {}
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    ed = MacroTextEdit()
    ed.setMinimumHeight(200)
    h.addWidget(ed)
    gear = QToolButton()
    gear.setIcon(icon("properties"))
    gear.setAutoRaise(True)
    gear.setToolTip("Provider, model and system instruction")
    gear.clicked.connect(lambda: _ai_settings(dlg))
    v = QVBoxLayout()
    v.addStretch(1)
    v.addWidget(gear)
    h.addLayout(v)
    ed.textChanged.connect(lambda: dlg._refresh() if hasattr(dlg, "ok_btn") else None)

    def setv(val):
        if isinstance(val, dict):
            ed.setPlainText(val.get("prompt", ""))
            dlg.extra.update({k: val.get(k, "") for k in ("provider", "model", "system")})
        else:
            ed.setPlainText(str(val))
    return box, lambda: {"prompt": ed.toPlainText(), **dlg.extra}, setv


spec(MacroSpec("ai_text", "AI text processing",
               lambda v: call("ai", (v.get("prompt") or {}).get("prompt", ""),
                              provider=(v.get("prompt") or {}).get("provider", ""),
                              model=(v.get("prompt") or {}).get("model", ""),
                              system=(v.get("prompt") or {}).get("system", "")),
               commands=("ai", "openai", "chatgpt"), width=445,
               parse=lambda a, o: {"prompt": {"prompt": a[0] if a else "", "provider": o.get("provider", ""),
                                              "model": o.get("model", ""), "system": o.get("system", "")}},
               description="Processes text with AI technology.",
               fields=[Text(text='Instruction ("Prompt"):'), Custom("prompt", factory=_ai_prompt_widget)]))

b, p = gen("document", args=("path",))
spec(MacroSpec("external_doc", "External document", b, commands=("document",), parse=p, process_output=False,
               description="Inserts the defined document into the phrase.",
               fields=[FilePath("path", "File path:", required=True,
                                filter="Documents (*.docx *.rtf *.txt *.html *.htm);;All files (*)")]))
b, p = gen("textfile", args=("path",))
spec(MacroSpec("embed_file", "Embed file contents", b, commands=("textfile", "embed", "embedfile"), parse=p,
               description="Embeds the file contents into the phrase",
               fields=[FilePath("path", "File path:", required=True)]))

RANGE_FIELDS = [Spin("fromrow", "From row:", minimum=1, default=1, width=336),
                Spin("torow", "To row:", minimum=1, default=1, width=336),
                Spin("fromcol", "From column:", minimum=1, default=1, width=336),
                Spin("tocol", "To column:", minimum=1, default=1, width=336)]


def _multi(v):
    return int(v.get("torow") or 1) > int(v.get("fromrow") or 1) or int(v.get("tocol") or 1) > int(v.get("fromcol") or 1)


def _range_opts(v):
    o = {k: v.get(k) for k in ("fromrow", "torow", "fromcol", "tocol")}
    if _multi(v):
        o["colsep"], o["rowsep"] = v.get("colsep"), v.get("rowsep")
    return o


def _range_parse(a, o):
    v = {"file": a[0] if a else "", "sheet": o.get("sheet", "1"), "colsep": o.get("colsep", ", "),
         "rowsep": o.get("rowsep", "")}
    for k in ("fromrow", "torow", "fromcol", "tocol"):
        v[k] = int(o.get(k, "1") or 1)
    return v


spec(MacroSpec("excel_cells", "MS Excel cells", lambda v: call("xls", v.get("file"), sheet=v.get("sheet") or "1",
                                                                **_range_opts(v)),
               commands=("xls",), parse=_range_parse,
               fields=[FilePath("file", "File:", required=True, filter="Excel (*.xlsx *.xlsm);;All files (*)"),
                       Line("sheet", "Sheet:", default="1")] + RANGE_FIELDS +
                      [Line("colsep", "Column separator:", default=", ", enabled_if=("tocol", lambda x: True)),
                       Line("rowsep", "Row separator:", default="\\n")]))
spec(MacroSpec("csv", "CSV data", lambda v: call("csv", v.get("file"), **_range_opts(v)), commands=("csv",),
               parse=_range_parse,
               fields=[FilePath("file", "File:", required=True, filter="CSV (*.csv *.txt);;All files (*)")] + RANGE_FIELDS +
                      [Line("colsep", "Column separator:", default=", "), Line("rowsep", "Row separator:", default="\\n")]))
b, p = gen("xml", args=("file",), opts=(("path", "xpath"),))
spec(MacroSpec("xml_xpath", "XML file XPATH content", b, commands=("xml",), parse=p,
               fields=[FilePath("file", "File:", required=True, filter="XML (*.xml);;All files (*)"),
                       Line("xpath", "XPath:", required=True, placeholder="./item/name")]))
for _k, _t, _c in (("find_excel_col", "Find MS Excel column", "xlsfindcol"),
                   ("find_excel_row", "Find MS Excel row", "xlsfindrow")):
    b, p = gen(_c, args=("file", "search"), opts=(("sheet", "sheet"),))
    spec(MacroSpec(_k, _t, b, commands=(_c,), parse=p,
                   fields=[FilePath("file", "File:", required=True, filter="Excel (*.xlsx *.xlsm);;All files (*)"),
                           Line("search", "Search text:", required=True), Line("sheet", "Sheet:", default="1")]))


def build_db(v):
    o = {"engine": v.get("engine") or "sqlite", "database": v.get("database"), "server": v.get("server"),
         "port": v.get("port"), "sep": v.get("fsep") if v.get("fsep") != ", " else "",
         "rowsep": "" if v.get("rsep") in ("", "New line", "\\n") else v.get("rsep")}
    if (v.get("engine") or "") not in ("sqlite", "odbc"):
        if v.get("auth") == "os":
            o["osauth"] = True
        else:
            o["user"], o["password"] = v.get("user"), v.get("password")
    if v.get("engine") == "odbc":
        o["connection"] = v.get("server")
        o.pop("server")
    return call("dbquery", v.get("query"), **o)


def _db_test(dlg, query_only: bool):
    vals = dlg.values()
    if not query_only:
        vals = {**vals, "query": "SELECT 1"}
    try:
        from phraseforge.macros import MacroEngine
        from phraseforge.ui.macro_dialog_kit import PreviewHost
        out = MacroEngine(PreviewHost()).expand_to_text(build_db(vals))
        QMessageBox.information(dlg, "Database query", out if query_only else "Connection OK" if "[" not in out else out)
    except Exception as e:
        QMessageBox.warning(dlg, "Database query", str(e))


DB_ENGINES = [("MS SQL", "mssql"), ("MySQL", "mysql"), ("PostgreSQL", "postgresql"), ("MS Access", "access"),
              ("SQLite", "sqlite"), ("ODBC connection string", "odbc")]
spec(MacroSpec("db_query", "Database query", build_db, commands=("dbquery", "sql"), layout="form", width=416,
               parse=lambda a, o: {"query": a[0] if a else "", "engine": o.get("engine", "sqlite"),
                                   "database": o.get("database", ""), "server": o.get("server", o.get("connection", "")),
                                   "port": o.get("port", ""), "auth": "os" if "osauth" in o else "sql",
                                   "user": o.get("user", ""), "password": o.get("password", ""),
                                   "fsep": o.get("sep", ", "), "rsep": o.get("rowsep", "New line")},
               fields=[Combo("engine", "Engine", options=DB_ENGINES, width=180),
                       Line("database", "Database"), Line("server", "Server"), Line("port", "Port"),
                       Radio("auth", options=[("OS Authentification", "os"), ("SQL Authentification", "sql")],
                             default="sql"),
                       Line("user", "Username", enabled_if=("auth", "sql")),
                       Line("password", "Password", password=True, enabled_if=("auth", "sql")),
                       Button(label="Test connection", action=lambda d: _db_test(d, False)),
                       Memo("query", "Query", height=56, required=True),
                       Button(label="Test database query", action=lambda d: _db_test(d, True)),
                       Line("fsep", "Field separator", default=", "), Line("rsep", "Row separator", default="New line")]))


def _env_options():
    return [(f"%{k}%", k) for k in sorted(os.environ, key=str.upper)]


spec(MacroSpec("env_var", "Windows environment variable", lambda v: call("env", v.get("var")), commands=("env",),
               name="%ALLUSERSPROFILE%", parse=lambda a, o: {"var": a[0] if a else ""},
               name_fn=lambda v: f"%{v.get('var')}%" if v.get("var") else "Windows environment variable",
               fields=[Combo("var", "Variable:", editable=True, options_fn=_env_options, required=True,
                             default="ALLUSERSPROFILE"),
                       Preview(big=False, fn=lambda v: os.environ.get(str(v.get("var") or ""), ""))]))

AD_OPTIONS = [("Name", "name"), ("Email", "email"), ("Nickname", "nickname"), ("Telephone number", "telephone"),
              ("Street", "street"), ("ZIP code", "zip"), ("City", "city"), ("Company", "company"),
              ("Department", "department"), ("Job title", "title"), ("First name", "firstname"),
              ("Last name", "lastname"), ("Mobile", "mobile"), ("Country", "country"), ("Office", "office")]
spec(MacroSpec("ad_more", "ActiveDirectory value", lambda v: call("ad", v.get("attr")), commands=("ad",),
               parse=lambda a, o: {"attr": a[0] if a else ""},
               fields=[Combo("attr", "Value", options=AD_OPTIONS, editable=True, required=True),
                       Combo("user", "Value", options=["Current user"]),
                       Preview(big=False, fn=lambda v: preview_macro(call("ad", v.get("attr"))))]))

# ============================================================================ Output
spec(MacroSpec("random_text", "Random text",
               lambda v: call("randomtext", "|".join(lines_to_list(v.get("items")))),
               commands=("randomtext",), width=518,
               parse=lambda a, o: {"items": "\n".join((a[0] if a else "").split(o.get("sep", "|")))},
               description="This macro randomly outputs one of the following phrases (one per line):",
               fields=[Memo("items", height=56, required=True)]))
b, p = gen("gender", opts=(("male", "male"), ("female", "female"), ("neutral", "neutral")))
spec(MacroSpec("gender", "Gender-O-Matic", b, commands=("gender",), parse=p,
               fields=[Line("male", 'Male form (e.g. "He"):'), Line("female", 'Female form (e.g. "She"):'),
                       Line("neutral", 'Neutral form (e.g. "It"):')]))
spec(MacroSpec("output_file", "Output to file",
               lambda v: call("outputfile", v.get("path"), v.get("contents"), template=v.get("template"),
                              open=bool(v.get("open")), openpath=v.get("openpath") if v.get("open") else ""),
               commands=("outputfile",), process_output=False,
               parse=lambda a, o: {"path": a[0] if a else "", "contents": a[1] if len(a) > 1 else "",
                                   "template": o.get("template", ""), "open": "open" in o, "openpath": o.get("openpath", "")},
               fields=[FilePath("path", "Target file path" + RIGHT_CLICK + ":", mode="save", required=True),
                       FilePath("template", "MS Word .dot(x) template" + RIGHT_CLICK + ":",
                                filter="Word templates (*.dot *.dotx);;All files (*)"),
                       Memo("contents", "Contents" + RIGHT_CLICK + ":", height=160),
                       Check("open", "Open"), FilePath("openpath", enabled_if=("open", True))]))
b, p = gen("pastefile", args=("path",))
spec(MacroSpec("paste_file", "Paste file", b, commands=("pastefile",), parse=p, process_output=False,
               description="Pastes file using clipboard", fields=[FilePath("path", "File path:", required=True)]))

MSG_BUTTONS = [("OK", "ok"), ("OK, Cancel", "okcancel"), ("Yes, No", "yesno"), ("Yes, No, Cancel", "yesnocancel"),
               ("Retry, Cancel", "retrycancel"), ("Abort, Retry, Ignore", "abortretryignore")]


def _msg_buttons_widget(dlg):
    from phraseforge.macros.commands import MESSAGE_BUTTONS
    box = QGroupBox("Buttons:")
    v = QVBoxLayout(box)
    combo = QComboBox()
    for t, val in MSG_BUTTONS:
        combo.addItem(t, val)
    v.addWidget(combo)
    rows = QVBoxLayout()
    v.addLayout(rows)
    v.addStretch(1)
    state = {"phrases": {}}

    def rebuild():
        while rows.count():
            it = rows.takeAt(0)
            w = it.widget() or (it.layout() and None)
            if it.widget():
                it.widget().deleteLater()
        for b in MESSAGE_BUTTONS[combo.currentData()]:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(4, 2, 4, 2)
            rb = QRadioButton(b)
            rb.setChecked(True)
            rb.setEnabled(False)
            h.addWidget(rb)
            link = LinkLabel(state["phrases"].get(b.lower()) or "Select phrase")

            def pick(b=b, link=link):
                r = pick_phrase_or_folder(dlg, "phrase")
                if r:
                    state["phrases"][b.lower()] = r
                    link.setText(f'<a href="#">{r}</a>')
            link.clicked.connect(pick)
            h.addWidget(link)
            h.addStretch(1)
            rows.addWidget(row)
    combo.currentIndexChanged.connect(lambda *_: rebuild())
    rebuild()

    def setv(val):
        if isinstance(val, dict):
            state["phrases"] = dict(val.get("phrases", {}))
            i = combo.findData(val.get("buttons", "ok"))
            combo.setCurrentIndex(max(0, i))
            rebuild()
    return box, lambda: {"buttons": combo.currentData(), "phrases": dict(state["phrases"])}, setv


def build_message(v):
    btn = v.get("buttons") or {"buttons": "ok", "phrases": {}}
    o = {"title": v.get("title"), "buttons": btn["buttons"] if btn["buttons"] != "ok" else ""}
    from phraseforge.macros.commands import MESSAGE_BUTTONS
    for b in MESSAGE_BUTTONS.get(btn["buttons"], ["OK"]):
        if btn["phrases"].get(b.lower()):
            o["on" + b.lower()] = btn["phrases"][b.lower()]
    return call("message", v.get("text"), **o)


spec(MacroSpec("message_box", "Message box", build_message, commands=("message", "msgbox"),
               parse=lambda a, o: {"text": a[0] if a else "", "title": o.get("title", ""),
                                   "buttons": {"buttons": o.get("buttons", "ok"),
                                               "phrases": {k[2:]: v for k, v in o.items() if k.startswith("on")}}},
               description="Opens a message box with customizable text and optional confirmation buttons. The "
                           "output text may consist of other macro functions that can be added by right-clicking "
                           "into the input field.",
               fields=[Line("title", "Window title text:"), Memo("text", "Message text" + RIGHT_CLICK + ":", height=70),
                       Custom("buttons", factory=_msg_buttons_widget)]))
spec(MacroSpec("notification", "Notification",
               lambda v: call("notify", v.get("title"), v.get("text"), click=v.get("click")),
               commands=("notify",), process_output=False,
               parse=lambda a, o: {"title": a[0] if a else "", "text": a[1] if len(a) > 1 else "",
                                   "click": o.get("click", "")},
               fields=[Line("title", "Title" + RIGHT_CLICK + ":"), Memo("text", "Text:", height=86),
                       Memo("click", "Output, if notification is clicked:", height=86)]))


def _ascii_options():
    out = []
    for i in list(range(32, 127)) + list(range(160, 256)):
        out.append((f"{i} - {chr(i)}" if i != 32 else "32 - (space)", str(i)))
    return out


spec(MacroSpec("ascii", "ASCII character", lambda v: call("ascii", v.get("code")), commands=("ascii",),
               parse=lambda a, o: {"code": a[0] if a else ""},
               description="Outputs a character as defined by its ASCII value",
               fields=[Combo("code", "Character:", options_fn=_ascii_options, editable=True, width=238, required=True)]))
spec(MacroSpec("random_number", "Random number", lambda v: call("random", "0", v.get("max")), commands=("random",),
               parse=lambda a, o: {"max": int(a[1]) if len(a) > 1 and a[1].lstrip("-").isdigit() else 1},
               description="Outputs a random integer value between 0 and the value specified",
               fields=[Spin("max", default=1, minimum=0, width=336)]))
spec(MacroSpec("cursor_pos", "Set cursor position", lambda v: "{#cursor}", commands=("cursor",), direct=True))
spec(MacroSpec("paste_method", "Set paste method",
               lambda v: call("pastemethod", v.get("method") or "auto",
                              delay=v.get("delay") if v.get("method") == "type" and v.get("delay") else ""),
               commands=("pastemethod",), process_output=False,
               parse=lambda a, o: {"method": a[0] if a else "auto", "delay": int(o.get("delay", "0") or 0)},
               description="Overrides the general paste settings for this particular phrase.\nIMPORTANT: This macro "
                           "must be located at the beginning of the phrase.",
               fields=[Radio("method", options=[("Automatic", "auto"), ("Simulate key presses (key-by-key)", "type"),
                                                ("Paste via the clipboard", "paste")], title="Paste method"),
                       Row(fields=[Text(text="Delay between key presses:"),
                                   Spin("delay", width=50, enabled_if=("method", "type")), Text(text="ms")])]))


def _keyboard_layouts():
    langs = [("Arabic (Saudi Arabia)", "ar-SA"), ("English (United States)", "en-US"), ("English (United Kingdom)", "en-GB"),
             ("French (France)", "fr-FR"), ("German (Germany)", "de-DE"), ("Spanish (Spain)", "es-ES"),
             ("Russian (Russia)", "ru-RU"), ("Turkish (Turkey)", "tr-TR"), ("Urdu (Pakistan)", "ur-PK"),
             ("Persian (Iran)", "fa-IR"), ("Chinese (Simplified)", "zh-CN"), ("Japanese", "ja-JP")]
    return langs


spec(MacroSpec("set_language", "Set language", lambda v: call("setlanguage", v.get("lang")),
               commands=("setlanguage",), process_output=False, parse=lambda a, o: {"lang": a[0] if a else ""},
               description="Select language to switch to",
               fields=[Combo("lang", "Language:", options_fn=_keyboard_layouts, editable=True, width=238, required=True)]))


def build_keypress(v):
    keys = [k for k in (v.get("modifier"), v.get("fkey") or (v.get("chars") or "").lower()) if k]
    return call("key", "+".join(keys), repeat=v.get("count") if str(v.get("count")) not in ("", "1") else "")


def parse_keypress(a, o):
    parts = (a[0] if a else "").split("+")
    mods = [p for p in parts if p in ("ctrl", "alt", "shift", "win")]
    key = next((p for p in parts if p not in mods), "")
    return {"modifier": "+".join(mods), "fkey": key if len(key) > 1 else "", "chars": key if len(key) == 1 else "",
            "count": o.get("repeat", "1")}


FKEYS = [""] + ["enter", "tab", "esc", "backspace", "delete", "insert", "home", "end", "pageup", "pagedown", "up",
                "down", "left", "right", "space", "win"] + [f"f{i}" for i in range(1, 13)]
spec(MacroSpec("keypress", "Keypress", build_keypress, commands=("key", "keys"), parse=parse_keypress,
               process_output=False, width=478,
               fields=[Row(fields=[Combo("modifier", "Modifier:", width=110, options=[
                   "", "shift", "ctrl", "alt", "win", "ctrl+shift", "ctrl+alt", "alt+shift", "ctrl+alt+shift"]),
                   Combo("fkey", "Function key:", options=FKEYS, width=120), Line("chars", "Chars:", width=92),
                   Line("count", "Count:", default="1", width=110)])]))


# ============================================================================ Automation
def build_email(v):
    o = {"to": v.get("to"), "cc": v.get("cc"), "bcc": v.get("bcc"), "subject": v.get("subject"),
         "body": v.get("body"), "send": bool(v.get("send"))}
    if v.get("attach_mode") == "file":
        o["attach"] = v.get("attach")
    elif v.get("attach_mode") == "stored":
        o["attach"] = v.get("attach_stored")
    return call("mail", **o)


spec(MacroSpec("create_email", "Create email", build_email, commands=("mail",), layout="form", process_output=False,
               shortcut="Ctrl+E",
               parse=lambda a, o: {"to": o.get("to", a[0] if a else ""), "cc": o.get("cc", ""), "bcc": o.get("bcc", ""),
                                   "subject": o.get("subject", ""), "body": o.get("body", ""), "send": "send" in o,
                                   "attach_mode": "file" if o.get("attach") else "none", "attach": o.get("attach", "")},
               fields=[Line("to", "To"), Line("cc", "CC"), Line("bcc", "BCC"), Line("subject", "Subject"),
                       Radio("attach_mode", options=[("Attachment(s):", "file"), ("Attach file stored in PhraseForge", "stored"),
                                                     ("No attachment", "none")], default="none"),
                       FilePath("attach", "Attachment(s)", enabled_if=("attach_mode", "file")),
                       FilePath("attach_stored", "Stored file", enabled_if=("attach_mode", "stored")),
                       Memo("body", height=90), Check("send", "Force immediate dispatch")]))
spec(MacroSpec("open_web", "Open web page",
               lambda v: call("web", v.get("url"), browser=v.get("browser") if v.get("browser") != "default" else ""),
               commands=("web", "url"), process_output=False,
               parse=lambda a, o: {"url": a[0] if a else "", "browser": o.get("browser", "default")},
               fields=[Line("url", "URL:", required=True),
                       Combo("browser", "Browser:", options=[("Default browser", "default"), ("Google Chrome", "chrome"),
                                                             ("Microsoft Edge", "edge"), ("Mozilla Firefox", "firefox"),
                                                             ("Brave", "brave")]),
                       Check("wait", "Wait until page is loaded (not supported)", enabled_if=("url", lambda x: False)),
                       Spin("timeout", "Timeout (0 - no timeout):", suffix="ms", width=120,
                            enabled_if=("wait", True))]))
spec(MacroSpec("run_program", "Run program",
               lambda v: call("run", v.get("path"), args=v.get("params"), dir=v.get("workdir")),
               commands=("run",), process_output=False, shortcut="Ctrl+R",
               parse=lambda a, o: {"path": a[0] if a else "", "params": o.get("args", " ".join(a[1:])),
                                   "workdir": o.get("dir", "")},
               fields=[FilePath("path", "File path:", required=True, filter="Programs (*.exe *.bat *.cmd);;All files (*)"),
                       Line("params", "Parameters:"), FilePath("workdir", "Working directory:", mode="dir")]))
spec(MacroSpec("open_file", "Open file", lambda v: call("open", v.get("path")), commands=("open",),
               process_output=False, shortcut="Ctrl+O", parse=lambda a, o: {"path": " ".join(a)},
               description="This macro opens the specified file with the application that is associated to it.",
               fields=[FilePath("path", "File path:", required=True)]))
spec(MacroSpec("open_folder", "Open folder", lambda v: call("openfolder", v.get("path")), commands=("openfolder",),
               process_output=False, parse=lambda a, o: {"path": " ".join(a)},
               description="This macro opens the specified folder in Windows Explorer.",
               fields=[FilePath("path", "Folder path:", mode="dir", required=True)]))


def _processes():
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=5,
                             creationflags=0x08000000).stdout
        names = sorted({line.split('","')[0].strip('"').lower() for line in out.splitlines() if line})
        return [""] + names
    except Exception:
        return [""]


def _window_titles():
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        titles = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(h, _):
            if user32.IsWindowVisible(h):
                n = user32.GetWindowTextLengthW(h)
                if n:
                    b = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(h, b, n + 1)
                    titles.append(b.value)
            return True
        user32.EnumWindows(cb, 0)
        return [""] + sorted(set(titles))
    except Exception:
        return [""]


spec(MacroSpec("app_focus", "Set application focus",
               lambda v: call("focus", process=v.get("process"), title=v.get("title"),
                              state=v.get("state") if v.get("state") != "none" else ""),
               commands=("focus",), process_output=False,
               parse=lambda a, o: {"process": o.get("process", ""), "title": o.get("title", ""),
                                   "state": o.get("state", "none")},
               fields=[Combo("process", "Process:", editable=True, options_fn=_processes),
                       Combo("title", "Window title (alternatively):", editable=True, options_fn=_window_titles),
                       Combo("state", "Window state:", options=[("Do nothing", "none"), ("Normal", "normal"),
                                                                ("Maximized", "max"), ("Minimized", "min")])]))


def parse_loop_block(a, o):
    return {"count": a[0] if a else "2"}


spec(MacroSpec("macro_loop", "Macro loop",
               lambda v: "{#loop " + str(v.get("count") or 2) + "}" + (v.get("text") or "") + "{#endloop}",
               commands=("loop",), process_output=False, shortcut="Ctrl+L", parse=parse_loop_block,
               fields=[Memo("text", "Text" + RIGHT_CLICK + ":", height=190), Line("count", "Count:", default="2")]))


# ============================================================================ Programming
def build_insert(v):
    if v.get("embed") and v.get("source") == "phrase" and v.get("phrase") and get_store() is not None:
        p = get_store().find_phrase(v["phrase"])
        if p is not None:
            return p.content
    if v.get("source") == "autotext":
        return call("insert", autotext=v.get("autotext"))
    store = get_store()
    target = v.get("phrase") or ""
    is_folder = store is not None and target and store.find_phrase(target) is None
    if is_folder or v.get("target_kind") == "folder":
        pick = {"manual": "", "nth": str(v.get("nth") or 1), "random": "random"}[v.get("folder_mode") or "manual"]
        return call("insert", folder=target, pick=pick, same=bool(v.get("same")))
    return call("insert", target)


def _pick_target(dlg):
    r = pick_phrase_or_folder(dlg, "either")
    if r:
        dlg.setters["phrase"](r)


spec(MacroSpec("insert_phrase", "Insert phrase", build_insert, commands=("insert",), shortcut="Ctrl+I",
               parse=lambda a, o: {"source": "autotext" if "autotext" in o else "phrase",
                                   "phrase": o.get("folder", a[0] if a else ""), "autotext": o.get("autotext", ""),
                                   "target_kind": "folder" if "folder" in o else "phrase",
                                   "folder_mode": "random" if o.get("pick") == "random" else
                                   "nth" if (o.get("pick") or "").isdigit() else "manual",
                                   "nth": int(o.get("pick")) if (o.get("pick") or "").isdigit() else 1,
                                   "same": "same" in o},
               description="Insert another phrase identified directly or by its Autotext.",
               fields=[Group(title="Select phrase(folder)", fields=[
                   Radio("source", options=[("Select phrase(folder)", "phrase"),
                                            ("Autotext of the desired phrase:", "autotext")]),
                   PickPhrase("phrase", kind="either", enabled_if=("source", "phrase")),
                   Line("autotext", width=110, enabled_if=("source", "autotext"))]),
                   Group(title="Folder options", enabled_if=("phrase", lambda x: bool(x)), fields=[
                       Text(text="If you selected a phrase folder or multiple phrases, define here, which of the "
                                 "multiple choices you wish to insert:"),
                       Radio("folder_mode", options=[("Manually select the desired phrase", "manual"),
                                                     ("Automatically insert the Nth phrase", "nth"),
                                                     ("Automatically select a phrase by random", "random")]),
                       Spin("nth", "N:", minimum=1, default=1, width=60, enabled_if=("folder_mode", "nth"))]),
                   Check("same", "Same output for all instances of this #insert macro (if\n"
                                 "re-used multiple times in the phrase)"),
                   Check("embed", "Embed phrase output into target phrase (vs. linking)")]))

OPS = [("Text equals", "=="), ("Text not equal", "!="), ("Text contains", "contains"),
       ("Text does not contain", "!contains"), ("Text begins with", "startswith"), ("Text ends with", "endswith"),
       ("Number equals", "=="), ("Number greater than", ">"), ("Number less than", "<"),
       ("Number greater or equal", ">="), ("Number less or equal", "<="), ("Matches RegEx", "=~"),
       ("Is empty", "empty"), ("Is not empty", "notempty")]
OP_LABEL = {}
for _t, _o in OPS:
    OP_LABEL.setdefault(_o, _t)


def _cond(a, op, b) -> str:
    if op in ("empty", "notempty"):
        return f"{op} {q(a)}"
    return f"{q(a)} {op} {q(b)}"


def build_check(v):
    return ("{#if " + _cond(v.get("contents"), v.get("op") or "==", v.get("cond")) + "}" + (v.get("then") or "") +
            ("{#else}" + v["else"] if v.get("else") else "") + "{#endif}")


spec(MacroSpec("check_value", "Check text/value", build_check, commands=(), width=736,
               fields=[Memo("contents", "Contents to compare:", height=44,
                            placeholder="Enter text to compare (Right-click to insert macro)..."),
                       Row(fields=[Combo("op", options=OPS, width=142),
                                   Memo("cond", height=46, placeholder="Enter conditional text (Right-click to insert macro)..."),
                                   Text(text="then"),
                                   Memo("then", height=46, placeholder="Enter output text if condition is true "
                                                                       "(Right-click to insert macro)...")]),
                       Text(text=""), Text(text=""),
                       Memo("else", "...else output:", height=44,
                            placeholder="Enter output text if condition is false (Right-click to insert macro)...")]))


def _conditions_widget(dlg):
    from phraseforge.ui.macro_dialog_kit import MacroLineEdit
    box = QWidget()
    outer = QVBoxLayout(box)
    outer.setContentsMargins(0, 0, 0, 0)
    rows: list[dict] = []

    def add_row(a="", op="==", b="", join="and", after=None):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        joiner = QComboBox()
        joiner.addItem("And", "and")
        joiner.addItem("Or", "or")
        joiner.setCurrentIndex(0 if join == "and" else 1)
        joiner.setFixedWidth(56)
        joiner.setVisible(bool(rows))
        h.addWidget(joiner)
        ea, eb = MacroLineEdit(a), MacroLineEdit(b)
        cb = QComboBox()
        for t, o in OPS:
            cb.addItem(t, o)
        cb.setCurrentIndex(max(0, cb.findData(op)))
        cb.setFixedWidth(142)
        minus, plus = QToolButton(), QToolButton()
        minus.setIcon(icon("remove", "#d6336c"))
        plus.setIcon(icon("add"))
        for b_ in (minus, plus):
            b_.setAutoRaise(True)
        for w in (ea, cb, eb, minus, plus):
            h.addWidget(w)
        rec = {"w": row, "a": ea, "op": cb, "b": eb, "join": joiner}
        rows.append(rec)
        outer.addWidget(row)
        plus.clicked.connect(lambda: add_row())
        minus.clicked.connect(lambda: remove(rec))
        cb.currentIndexChanged.connect(lambda *_: eb.setEnabled(cb.currentData() not in ("empty", "notempty")))

    def remove(rec):
        if len(rows) > 1:
            rows.remove(rec)
            rec["w"].deleteLater()
            rows[0]["join"].setVisible(False)

    add_row()

    def get():
        return [{"a": r["a"].text(), "op": r["op"].currentData(), "b": r["b"].text(), "join": r["join"].currentData()}
                for r in rows]

    def setv(conds):
        for r in list(rows):
            rows.remove(r)
            r["w"].deleteLater()
        for c in conds or [{}]:
            add_row(c.get("a", ""), c.get("op", "=="), c.get("b", ""), c.get("join", "and"))
    return box, get, setv


def build_if(v):
    conds = v.get("conds") or [{"a": "", "op": "==", "b": ""}]
    expr = ""
    for i, c in enumerate(conds):
        part = _cond(c["a"], c["op"], c["b"])
        expr = part if i == 0 else f"{expr} {c.get('join') or 'and'} {part}"
    return "{#if " + expr + "}" + (v.get("then") or "") + ("{#else}" + v["else"] if v.get("else") else "") + "{#endif}"


spec(MacroSpec("if_then_else", "If-Then-Else", build_if, commands=("if",), width=670,
               fields=[Custom("conds", factory=_conditions_widget), Memo("then", "Then" + RIGHT_CLICK + ":", height=70),
                       Memo("else", "Else" + RIGHT_CLICK + ":", height=50)]))

ROUND_TO = [("Use system settings (2)", ""), ("0", "0"), ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5"),
            ("6", "6"), ("8", "8"), ("10", "10")]
DEC_SEP = [('Use system settings (".")', ""), (". (point)", "."), (", (comma)", ",")]
THOU_SEP = [('Use system settings (",")', ""), ("(none)", ""), (", (comma)", ","), (". (point)", "."),
            ("Space", "space"), ("' (apostrophe)", "'")]


def build_calc(v):
    return call("calc", v.get("expr"), decimals=v.get("round"), zeros=v.get("zeros") if v.get("zeros") else "",
                decsep=v.get("decsep"), thousands=v.get("thousands"))


spec(MacroSpec("calculation", "Calculation", build_calc, commands=("calc",),
               parse=lambda a, o: {"expr": " ".join(a), "round": o.get("decimals", ""), "zeros": int(o.get("zeros", 0) or 0),
                                   "decsep": o.get("decsep", ""), "thousands": o.get("thousands", "")},
               description="Returns the result of the mathematical expression. Example: 3+4*6 would output 27.",
               fields=[Memo("expr", "Expression" + RIGHT_CLICK + ":", height=40, required=True),
                       Group(title="Number output formatting", fields=[
                           Row(fields=[Spin("zeros", "Left-hand zeros:", width=130),
                                       Combo("round", "Round to:", options=ROUND_TO, width=140)]),
                           Row(fields=[Combo("decsep", "Decimal separator:", options=DEC_SEP, width=130),
                                       Combo("thousands", "Thousands separator:", options=THOU_SEP, width=140)])]),
                       Preview()]))
spec(MacroSpec("set_phrase_content", "Set phrase content",
               lambda v: call("setphrase", v.get("description"), v.get("content"), target=v.get("target"),
                              folder=v.get("folder")),
               commands=("setphrase",), process_output=False,
               parse=lambda a, o: {"description": a[0] if a else "", "content": a[1] if len(a) > 1 else "",
                                   "target": o.get("target", ""), "folder": o.get("folder", "")},
               fields=[Line("description", "Description:"), Memo("content", "Phrase content" + RIGHT_CLICK + ":", height=96),
                       PickPhrase("target", "Target phrase:", kind="phrase"),
                       PickPhrase("folder", "Parent folder:", kind="folder")]))
spec(MacroSpec("wait", "Wait x milliseconds", lambda v: call("sleep", v.get("delay")), commands=("sleep", "wait"),
               process_output=False, parse=lambda a, o: {"delay": int(a[0]) if a and a[0].isdigit() else 3000},
               name_fn=lambda v: f"Wait {v.get('delay') or 0} milliseconds",
               fields=[Spin("delay", "Delay:", default=3000, suffix="ms", width=210)]))


def _var_names():
    store = get_store()
    names = sorted({r["name"] for r in store.all_vars()}) if store is not None else []
    return [""] + names


def build_set_var(v):
    s = call("set", v.get("name"), v.get("content"), scope="global" if v.get("global") else "")
    return s + (call("var", v.get("name")) if v.get("output") else "")


spec(MacroSpec("set_variable", "Set variable", build_set_var, commands=("set",),
               parse=lambda a, o: {"name": a[0] if a else "", "content": a[1] if len(a) > 1 else "",
                                   "global": o.get("scope") == "global"},
               fields=[Combo("name", "Variable name:", editable=True, options_fn=_var_names, width=284, required=True),
                       Memo("content", "Variable content:", height=120),
                       Check("output", "Output variable content directly"),
                       Check("global", "Keep the value after the phrase ends (global variable)")]))
spec(MacroSpec("output_variable", "Output variable", lambda v: call("var", v.get("name")), commands=("var", "get"),
               show_name=False, shortcut="Ctrl+G", parse=lambda a, o: {"name": a[0] if a else ""},
               fields=[Combo("name", "Variable name:", editable=True, options_fn=_var_names, required=True)]))

# ============================================================================ Text operations
text_spec("text_length", "Text length", "length")
spec(MacroSpec("substring", "Substring", lambda v: call("substr", v.get("text"), v.get("start"), v.get("length")),
               commands=("substr",),
               parse=lambda a, o: {"text": a[0] if a else "", "start": int(a[1]) if len(a) > 1 else 1,
                                   "length": int(a[2]) if len(a) > 2 else 1},
               fields=[Memo("text", "Text" + RIGHT_CLICK + ":", height=96),
                       Row(fields=[Spin("start", "Split beginning from:", minimum=-99999, default=1, width=80),
                                   Spin("length", "Text length:", default=1, width=80)])]))


def _regex_presets(dlg):
    from PySide6.QtWidgets import QMenu
    btn = QToolButton()
    btn.setIcon(icon("add"))
    btn.setAutoRaise(True)
    btn.setPopupMode(QToolButton.InstantPopup)
    m = QMenu(btn)
    for t, pat in (("Email address", r"[\w.+-]+@[\w-]+\.[\w.-]+"), ("Number", r"-?\d+(?:[.,]\d+)?"),
                   ("Web address", r"https?://\S+"), ("Date (dd.mm.yyyy)", r"\d{1,2}\.\d{1,2}\.\d{4}"),
                   ("Phone number", r"\+?[\d\s()/-]{6,}"), ("Word", r"\w+"), ("Line", r".+")):
        m.addAction(t, lambda pat=pat: dlg.setters["regex"](pat))
    btn.setMenu(m)
    return btn, lambda: None, lambda v: None


spec(MacroSpec("regex_extract", "Extract substring with RegEx",
               lambda v: call("regexget", v.get("text"), v.get("regex"), all=bool(v.get("all")),
                              sep=v.get("sep") if v.get("all") else ""),
               commands=("regexget",),
               parse=lambda a, o: {"text": a[0] if a else "", "regex": a[1] if len(a) > 1 else "", "all": "all" in o,
                                   "sep": o.get("sep", "")},
               fields=[Memo("text", "Text" + RIGHT_CLICK + ":", height=130),
                       Row(fields=[Memo("regex", "RegEx Expression:", height=64, macro_menu=False),
                                   Custom("_presets", factory=_regex_presets)]),
                       Check("all", "Find all"), Line("sep", "Separator:", default=", ", enabled_if=("all", True))]))
text_spec("trim", "Trim", "trim")
text_spec("trim_leading", "Trim leading spaces", "ltrim")
text_spec("trim_trailing", "Trim trailing spaces", "rtrim")


def build_replace(v):
    if v.get("regex"):
        return call("regexreplace", v.get("source"), v.get("search"), v.get("replacement") or "")
    return call("replace", v.get("source"), v.get("search"), v.get("replacement") or "")


def _three_arg_values(a, o, regex=False):
    return {"source": a[0] if a else "", "search": a[1] if len(a) > 1 else "",
            "replacement": a[2] if len(a) > 2 else "", "regex": regex}


spec(MacroSpec("replace", "Replace text", build_replace, commands=("replace",), parse=_three_arg_values,
               fields=[Memo("source", "Source String" + RIGHT_CLICK + ":", height=46),
                       Memo("search", "Search string" + RIGHT_CLICK + ":", height=40), Check("regex", "RegEx"),
                       Memo("replacement", "Replacement string:", height=40)]))
SPECS["replace"].commands = ("replace", "regexreplace")
SPECS["replace"].parse = lambda a, o: _three_arg_values(a, o, False)


def _pos_spec(kind, title, cmd):
    spec(MacroSpec(kind, title, lambda v: call(cmd, v.get("text"), v.get("sub"), regex=bool(v.get("regex"))),
                   commands=(cmd,),
                   parse=lambda a, o: {"text": a[0] if a else "", "sub": a[1] if len(a) > 1 else "", "regex": "regex" in o},
                   fields=[Memo("text", "Text" + RIGHT_CLICK + ":", height=96), Memo("sub", "Sub string:", height=70),
                           Check("regex", "RegEx")]))


_pos_spec("substring_pos", "Substring position", "strpos")
_pos_spec("last_pos", "Last position", "lastpos")
text_spec("sentence_case", "Begin sentences with uppercase", "sentence")
text_spec("upper", "Convert to UPPER CASE", "upper")
text_spec("lower", "Convert to lower case", "lower")
text_spec("upper_first", "UPPER CASE first character", "ucfirst")
text_spec("lower_first", "lower case first character", "lcfirst")
text_spec("upper_words", "UPPER CASE first char of each word", "ucwords")
text_spec("lower_words", "lower case first char of each word", "lcwords")

# ============================================================================ Clipboard
CLIP_KEYS = {"cut": "ctrl+x", "copy": "ctrl+c", "paste": "ctrl+v"}
spec(MacroSpec("paste_copy", "Clipboard paste/copy", lambda v: call("key", CLIP_KEYS[v.get("action") or "paste"]),
               commands=(), process_output=False,
               fields=[Radio("action", options=[("Cut", "cut"), ("Copy", "copy"), ("Paste", "paste")], title="Actions",
                             default="paste")]))
spec(MacroSpec("insert_from_clipboard", "Insert text from clipboard",
               lambda v: "{#clipboard}" if v.get("source") != "cache" else call("clipboardhistory", int(v.get("item") or 1) - 1),
               commands=("clipboard", "clipboardhistory", "insertclipboard"), width=465,
               parse=lambda a, o: {"source": "cache" if a else "windows", "item": int(a[0]) + 1 if a and a[0].isdigit() else 1},
               fields=[Radio("source", options=[("Use Windows clipboard", "windows"),
                                                ("Use PhraseForge clipboard cache", "cache")]),
                       Row(fields=[Text(text="Item to retrieve (ordered by most recent):"),
                                   Spin("item", minimum=1, maximum=1024, default=1, width=60,
                                        enabled_if=("source", "cache"))])]))
text_spec("put_into_clipboard", "Put text into clipboard", "setclipboard")

# ============================================================================ Screen OCR (replaces "Macro Recorder")


def _ocr_languages():
    try:
        from phraseforge.ocr import Capture2TextOCR
        store = get_store()
        path = store.setting("ocr.cli_path") if store is not None else ""
        langs = Capture2TextOCR(path).languages()
        if langs:
            return langs
    except Exception:
        pass
    return ["English", "Arabic", "Russian"]


def build_ocr(v):
    if v.get("source") == "file":
        return call("ocrfile", v.get("path"), lang=v.get("lang"))
    return call("ocr", lang=v.get("lang"), linebreaks=bool(v.get("linebreaks")))


spec(MacroSpec("ocr", "Screen OCR", build_ocr, commands=("ocr", "ocrfile"),
               parse=lambda a, o: {"source": "file" if a else "screen", "path": a[0] if a else "",
                                   "lang": o.get("lang", ""), "linebreaks": "linebreaks" in o},
               description="Recognizes text on screen (Capture2Text). When the phrase runs you drag a rectangle "
                           "around the text to read.",
               fields=[Radio("source", options=[("Select a screen region when the phrase runs", "screen"),
                                                ("Read an image file", "file")]),
                       FilePath("path", "Image file:", enabled_if=("source", "file"),
                                filter="Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*)"),
                       Combo("lang", "Language:", options_fn=_ocr_languages), Check("linebreaks", "Keep line breaks",
                                                                                   default=True)]))
