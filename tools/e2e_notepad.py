"""End-to-end check: PhraseForge expands an abbreviation typed into Notepad."""
import ctypes, os, subprocess, sys, tempfile, time  # run: C:\venvs\phraseforge\Scripts\python.exe tools\e2e_notepad.py
from ctypes import wintypes

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
home = tempfile.mkdtemp(prefix="pf_e2e_")
os.environ["PHRASEFORGE_HOME"] = home

from phraseforge.db import Store
from phraseforge.models import Phrase, Trigger, TriggerKind, AutotextMode
s = Store(os.path.join(home, "phrases.db"))
s.set_setting("app.first_run_done", "1")
s.add_phrase(Phrase("Year", "Year {#date -format yyyy}!", triggers=[Trigger(TriggerKind.AUTOTEXT, "pf;", mode=AutotextMode.IMMEDIATE, word_start_only=False)]))
s.add_phrase(Phrase("Greet", "Hello {#upper world}", triggers=[Trigger(TriggerKind.AUTOTEXT, "hw", mode=AutotextMode.DELIMITER)]))
s.close()

user32 = ctypes.windll.user32
app = subprocess.Popen([r"C:\venvs\phraseforge\Scripts\python.exe", "-X", "faulthandler", "-m", "phraseforge", "--minimized"],
                       cwd=PROJ, env=os.environ.copy(), stderr=open(os.path.join(home, "err.txt"), "w"))
# wait until the app has installed its keyboard hook (it logs "triggers ready")
_log = os.path.join(home, "phraseforge.log")
for _ in range(300):
    if os.path.exists(_log) and "triggers ready" in open(_log, encoding="utf-8", errors="replace").read():
        break
    time.sleep(0.1)
else:
    print("WARNING: app never logged 'triggers ready'")
time.sleep(0.5)
np = subprocess.Popen(["notepad.exe"])

def fg_class():
    b = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(user32.GetForegroundWindow(), b, 64)
    return b.value

for _ in range(100):           # wait until Notepad really owns the foreground
    if fg_class() == "Notepad":
        break
    time.sleep(0.1)
time.sleep(1.5)
print("FOREGROUND:", fg_class())
# start from an empty document (Win11 Notepad may restore old tabs): new tab
user32.keybd_event(0x11, 0, 0, 0); user32.keybd_event(0x4E, 0, 0, 0)
user32.keybd_event(0x4E, 0, 2, 0); user32.keybd_event(0x11, 0, 2, 0)
time.sleep(1.0)

# --- plain SendInput (no PhraseForge marker), like a real user typing
class KI(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]

def key(vk, up=False):
    i = INPUT(type=1); i.ki = KI(vk, 0, 2 if up else 0, 0, 0)
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))

def type_vk(text):
    for ch in text:
        r = user32.VkKeyScanW(ord(ch))
        vk, shift = r & 0xFF, (r >> 8) & 1
        if shift: key(0x10)
        key(vk); key(vk, True)
        if shift: key(0x10, True)
        time.sleep(0.04)

type_vk("pf;")
time.sleep(1.2)
type_vk(" hw ")
time.sleep(1.5)

# read Notepad text (classic Edit or Win11 RichEditD2DPT)
def notepad_text():
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum(h, _):
        buf = ctypes.create_unicode_buffer(64); user32.GetClassNameW(h, buf, 64)
        if buf.value in ("Edit", "RichEditD2DPT"):
            found.append(h)
        return True
    fg = user32.GetForegroundWindow()
    user32.EnumChildWindows(fg, enum, 0)
    for h in found:
        n = user32.SendMessageW(h, 0x000E, 0, 0)
        b = ctypes.create_unicode_buffer(n + 1)
        user32.SendMessageW(h, 0x000D, n + 1, b)
        if b.value:
            return b.value
    return "" if not found else "<empty>"

text = notepad_text()
print("NOTEPAD:", repr(text))
expected = f"Year {time.strftime('%Y')}! Hello WORLD "
print("PASS" if text == expected else f"FAIL expected {expected!r}")
log = os.path.join(home, "phraseforge.log")
print("LOG:", open(log, encoding="utf-8").read()[-2000:] if os.path.exists(log) else "(none)")
print("APP RUNNING:", app.poll() is None, app.poll())
err=open(os.path.join(home,"err.txt")).read()
print("ERR:", "\n".join(l for l in err.splitlines() if "threading.py" not in l)[:4000])
# close notepad without saving, stop app
key(0x12); key(0x73); key(0x73, True); key(0x12, True); time.sleep(0.8); key(0x4E); key(0x4E, True)
time.sleep(0.5)
app.terminate()
np.kill() if np.poll() is None else None

