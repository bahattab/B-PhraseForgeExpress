"""Command-line switches (PRD FR-APP-02).

Start-up switches (this process only):
  --portable, --home <dir>   data folder (paths.apply_command_line, read before anything else)
  --minimized                start in the tray, no main window
  --hidden                   no main window and no tray icon (a later launch shows the window)
  --no-hook                  do not watch the keyboard: no autotext or hotkeys
  --no-clipboard             do not watch the clipboard (no clipboard history or triggers)
  --readonly                 phrases and folders cannot be changed (like the editing_disabled policy)
  --debug                    DEBUG logging; --log-file <path> writes the log there

Actions (also handed to an already running PhraseForge):
  --shutdown                 ask the running PhraseForge to exit
  --import <file>            import a PhraseExpress or PhraseForge file
  --open <phrase file>       mount another phrase file as a read-only library
  --exec <uid|description>   insert that phrase into the program in front
  --edit <uid|description>   open the main window on that phrase
  phraseforge://exec/<uid>   the same as --exec, for links (Windows URL protocol, opt-in:
                             --register-url / --unregister-url; refused in portable mode)
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)
FLAGS = ("minimized", "hidden", "no-hook", "no-clipboard", "readonly", "debug", "shutdown",
         "self-test", "register-url", "unregister-url")
VALUED = ("import", "open", "exec", "edit", "log-file")
URL_SCHEME = "phraseforge"


class UsageError(ValueError):
    pass


@dataclass
class Options:
    flags: set[str] = field(default_factory=set)
    imports: list[str] = field(default_factory=list)
    opens: list[str] = field(default_factory=list)
    execs: list[str] = field(default_factory=list)
    edits: list[str] = field(default_factory=list)
    url_execs: list[str] = field(default_factory=list)   # from a phraseforge:// link: asked first
    log_file: str = ""
    rest: list[str] = field(default_factory=list)    # anything else (left for Qt)

    def has(self, flag: str) -> bool:
        return flag in self.flags

    @property
    def actions(self) -> bool:
        """Something for the running PhraseForge to do (rather than just "show yourself")."""
        return bool(self.imports or self.opens or self.execs or self.url_execs or self.edits or self.has("shutdown"))


def parse_url(url: str) -> tuple[str, str] | None:
    """phraseforge://exec/<uid> -> ("exec", uid); also edit. None for anything else."""
    u = urlparse(url)
    if u.scheme.lower() != URL_SCHEME:
        return None
    verb = (u.netloc or "").lower()
    arg = unquote(u.path.lstrip("/"))
    if not arg and "/" in verb:
        verb, _, arg = verb.partition("/")
    if verb in ("exec", "edit") and arg:
        return verb, arg
    return None


def parse(argv: list[str]) -> Options:
    """argv without the program name. Raises UsageError for a switch missing its value."""
    o = Options()
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if name in FLAGS and not eq:
                o.flags.add(name)
            elif name in VALUED:
                if not eq:
                    if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
                        raise UsageError(f"--{name} needs a value")
                    i += 1
                    val = argv[i]
                if name == "log-file":
                    o.log_file = val
                else:
                    {"import": o.imports, "open": o.opens, "exec": o.execs, "edit": o.edits}[name].append(val)
            else:
                o.rest.append(a)
        elif (hit := parse_url(a)) is not None:
            (o.url_execs if hit[0] == "exec" else o.edits).append(hit[1])
        else:
            o.rest.append(a)
        i += 1
    return o


def forwarded(o: Options) -> list[str]:
    """The switches a later launch hands to the running PhraseForge."""
    out = [f"--{f}" for f in ("shutdown", "minimized", "hidden") if o.has(f)]
    for name, values in (("import", o.imports), ("open", o.opens), ("exec", o.execs), ("edit", o.edits)):
        for v in values:
            out += [f"--{name}", v]
    out += [f"{URL_SCHEME}://exec/{v}" for v in o.url_execs]   # stays a link: still asked first
    return out


def configure_logging(o: Options, default_file: str) -> None:
    logging.basicConfig(filename=o.log_file or default_file, level=logging.DEBUG if o.has("debug") else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def find_phrase(store, key: str):
    """A phrase by uid, id or description."""
    key = (key or "").strip()
    if not key:
        return None
    p = store.phrase_by_uid(key) if hasattr(store, "phrase_by_uid") else None
    if p is None and key.isdigit():
        p = store.get_phrase(int(key))
    return p or store.find_phrase(key)


def _confirm_link(app, phrase) -> bool:
    """A web page can open phraseforge:// links, so a link never inserts a phrase unasked."""
    ask = getattr(app, "confirm_link_exec", None)
    if ask is not None:
        return bool(ask(phrase))
    from PySide6.QtWidgets import QMessageBox
    from phraseforge.ui.i18n import tr
    return QMessageBox.question(None, "PhraseForge", tr('A link asks to insert the phrase "{name}". Insert it?')
                                .replace("{name}", phrase.description)) == QMessageBox.Yes


def run_actions(app, o: Options) -> list[str]:
    """Do what the switches ask; returns a line per problem (shown in the tray)."""
    problems: list[str] = []
    if o.has("shutdown"):
        app.quit()
        return problems
    for path in o.imports:
        try:
            app.show_main()
            mw = app.main_window
            if str(path).lower().endswith(".json"):
                from phraseforge.io_formats import import_json
                import_json(app.store, path)
                mw.refresh_tree()
            elif mw.import_phraseexpress_path(path, show_message=False) is None:
                problems.append(f"could not import {path}")
        except Exception as e:                      # noqa: BLE001 - reported, the next switch still runs
            problems.append(f"could not import {path}: {e}")
    for path in o.opens:
        try:
            from phraseforge import libraries
            from pathlib import Path
            libraries.manager(app.store).add(Path(path).stem, path, "ro")
        except Exception as e:                      # noqa: BLE001
            problems.append(f"could not open {path}: {e}")
    for key in o.execs:
        p = find_phrase(app.store, key)
        if p is None:
            problems.append(f"no phrase {key!r}")
            continue
        from phraseforge.host import ExpansionRequest
        app.on_expand_request(ExpansionRequest(phrase_id=p.id))
    for key in o.url_execs:
        p = find_phrase(app.store, key)
        if p is None:
            problems.append(f"no phrase {key!r}")
        elif _confirm_link(app, p):
            from phraseforge.host import ExpansionRequest
            app.on_expand_request(ExpansionRequest(phrase_id=p.id))
    for key in o.edits:
        p = find_phrase(app.store, key)
        if p is None:
            problems.append(f"no phrase {key!r}")
            continue
        app.show_main()
        app.main_window.select_phrase(p.id)
    return problems


# ---------------------------------------------------------------- URL protocol (Windows, opt-in)
def _command() -> str:
    exe = sys.executable
    if getattr(sys, "frozen", False):
        return f'"{exe}" "%1"'
    return f'"{exe}" -m phraseforge "%1"'


def register_url_protocol(winreg=None) -> None:
    from phraseforge import paths
    paths.refuse_in_portable("register the phraseforge:// link type")
    if winreg is None:
        import winreg  # type: ignore
    base = r"Software\Classes\phraseforge"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:PhraseForge")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _command())


def unregister_url_protocol(winreg=None) -> None:
    from phraseforge import paths
    paths.refuse_in_portable("remove the phraseforge:// link type")
    if winreg is None:
        import winreg  # type: ignore
    base = r"Software\Classes\phraseforge"
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + sub)
        except OSError:
            pass
