"""Tiny translation helper. English strings are the keys; Arabic table below."""
from __future__ import annotations

import re

_LANG = "en"

AR = {
    "PhraseForge": "PhraseForge",
    "File": "ملف",
    "Tools": "أدوات",
    "Help": "مساعدة",
    "Import...": "استيراد...",
    "Export...": "تصدير...",
    "Backup...": "نسخ احتياطي...",
    "Restore...": "استعادة...",
    "Quit": "خروج",
    "Statistics": "الإحصاءات",
    "Clipboard history": "سجل الحافظة",
    "Suggestions": "الاقتراحات",
    "Variables": "المتغيرات",
    "Settings": "الإعدادات",
    "Language selection": "اختيار اللغة",
    "Enabled in": "مفعّل في",
    "About": "حول",
    "Search": "بحث",
    "New folder": "مجلد جديد",
    "New phrase": "عبارة جديدة",
    "Delete": "حذف",
    "Duplicate": "تكرار",
    "Enable / disable": "تفعيل / تعطيل",
    "Properties...": "خصائص...",
    "Description": "الوصف",
    "Content": "المحتوى",
    "Rich text": "نص منسق",
    "Insert macro": "إدراج ماكرو",
    "Triggers": "المشغلات",
    "Tags": "الوسوم",
    "Output": "الإخراج",
    "Notes": "ملاحظات",
    "Preview": "معاينة",
    "Save": "حفظ",
    "Revert": "تراجع",
    "History...": "السجل...",
    "Add": "إضافة",
    "Remove": "إزالة",
    "Only in apps": "فقط في التطبيقات",
    "Not in apps": "ليس في التطبيقات",
    "Enabled": "مفعل",
    "OK": "موافق",
    "Cancel": "إلغاء",
    "Open PhraseForge": "فتح PhraseForge",
    "Phrase menu": "قائمة العبارات",
    "OCR to clipboard": "التعرف الضوئي إلى الحافظة",
    "Pause": "إيقاف مؤقت",
    "General": "عام",
    "Autotext": "النص التلقائي",
    "Hotkeys": "اختصارات",
    "Learning": "التعلم",
    "OCR": "التعرف الضوئي",
    "Excluded apps": "التطبيقات المستثناة",
    "Test": "اختبار",
    "Browse...": "استعراض...",
    "Language": "اللغة",
    "Theme": "المظهر",
    "Create phrase": "إنشاء عبارة",
    "Dismiss": "تجاهل",
    "Pin": "تثبيت",
    "Clear": "مسح",
    "Restore": "استعادة",
    "Password": "كلمة المرور",
    "Folder properties": "خصائص المجلد",
    "Name": "الاسم",
    "Welcome": "مرحبا",
}


from phraseforge.ui.i18n_ar import AR_EXTRA  # noqa: E402

for _k, _v in AR_EXTRA.items():
    AR.setdefault(_k, _v)

RTL_LANGUAGES = {"ar", "he", "fa", "ur"}


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang or "en"


def resolve_language(setting: str, system_locale: str | None = None) -> str:
    """'auto' -> 'ar' when the system language is Arabic, else 'en'."""
    if setting and setting != "auto":
        return setting
    if system_locale is None:
        try:
            from PySide6.QtCore import QLocale
            system_locale = QLocale.system().name()
        except Exception:
            system_locale = ""
    return "ar" if (system_locale or "").lower().startswith("ar") else "en"


def is_rtl(lang: str | None = None) -> bool:
    return (lang or _LANG) in RTL_LANGUAGES


def language() -> str:
    return _LANG


def tr(text: str) -> str:
    if _LANG == "ar":
        return lookup(text)
    return text


def lookup(text: str) -> str:
    """Arabic for an English UI string; tolerant of '&' accelerators, a trailing
    '...', ':' or ' *', line breaks in ribbon captions and '(Ctrl+X)' hints."""
    if not text or not text.strip():
        return text
    hit = AR.get(text)
    if hit is not None:
        return hit
    core = text.replace("&&", "\0").replace("&", "").replace("\0", "&").replace("\u200f", "")
    if "<u>" in core:                                  # "<u>D</u>escription" captions
        core = re.sub(r"</?u>", "", core)
    lead = core[:len(core) - len(core.lstrip())]
    core = core.strip()
    for cand in (core, " ".join(core.split())):
        hit = AR.get(cand)
        if hit is not None:
            return lead + hit
    for suffix in ("...", "…", ":", " *", "*"):
        if core.endswith(suffix):
            base = core[:-len(suffix)].rstrip()
            hit = AR.get(base) or AR.get(" ".join(base.split()))
            if hit is not None:
                return lead + hit + suffix.strip()
    if core.endswith(")") and " (" in core:            # "Close (Esc)"
        base, hint = core.rsplit(" (", 1)
        hit = AR.get(base)
        if hit is not None:
            return f"{lead}{hit} ({hint}"
    return text


# ---------------------------------------------------------------- automatic widget translation
# Widgets are translated when Qt polishes them and again whenever a window or menu
# is shown, so dialogs built with English literals appear in Arabic without
# wrapping every string in tr(). The English originals are kept in dynamic
# properties so switching back to English restores them. Widgets holding user
# data set the property "pf_user" (they and their children are left alone);
# tree/list items are translated only when the view sets "pf_i18n".

_PROPS = (("text", "setText"), ("title", "setTitle"), ("placeholderText", "setPlaceholderText"),
          ("windowTitle", "setWindowTitle"), ("toolTip", "setToolTip"))


def _swap(obj, prop: str, getter, setter) -> None:
    key = "_pf_en_" + prop
    cur = getter()
    orig = obj.property(key)
    if orig is None or (cur != orig and cur != lookup(orig)):
        orig = cur                        # first time, or the program changed the text since
        if not isinstance(orig, str) or not orig:
            return
        obj.setProperty(key, orig)
    want = lookup(orig) if _LANG == "ar" else orig
    if want != cur:
        setter(want)


def _user_data(w) -> bool:
    while w is not None:
        if w.property("pf_user"):
            return True
        w = w.parentWidget()
    return False


def translate_widget(w) -> None:
    from PySide6.QtWidgets import (
        QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QMenu, QTabBar, QTabWidget,
        QTreeWidget, QListWidget, QTextEdit, QPlainTextEdit,
    )
    if _user_data(w):
        return
    try:
        if isinstance(w, (QLabel, QAbstractButton)):
            _swap(w, "text", w.text, w.setText)
        if isinstance(w, QGroupBox):
            _swap(w, "title", w.title, w.setTitle)
        if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit)):
            _swap(w, "placeholderText", w.placeholderText, w.setPlaceholderText)
        if w.isWindow():
            _swap(w, "windowTitle", w.windowTitle, w.setWindowTitle)
        if w.toolTip():
            _swap(w, "toolTip", w.toolTip, w.setToolTip)
        if isinstance(w, QTabWidget):
            w = w.tabBar()
        if isinstance(w, QTabBar):
            for i in range(w.count()):
                _swap_indexed(w, "tab", i, w.tabText, w.setTabText)
        elif isinstance(w, QComboBox) and not w.isEditable() and _combo_safe(w):
            for i in range(w.count()):
                _swap_indexed(w, "item", i, w.itemText, w.setItemText)
        elif isinstance(w, QMenu):
            translate_actions(w.actions())
            _swap(w, "title", w.title, w.setTitle)
        elif isinstance(w, QTreeWidget) and w.property("pf_i18n"):
            from PySide6.QtWidgets import QTreeWidgetItemIterator
            it = QTreeWidgetItemIterator(w)
            while it.value():
                item = it.value()
                for c in range(item.columnCount()):
                    _swap_item(item, c)
                it += 1
        elif isinstance(w, QListWidget) and w.property("pf_i18n"):
            for i in range(w.count()):
                _swap_item(w.item(i), 0)
        if w.actions():
            translate_actions(w.actions())
        if isinstance(w, QAbstractButton) and getattr(w, "menu", None) and w.menu() is not None:
            translate_actions(w.menu().actions())
    except RuntimeError:          # widget deleted while we looked at it
        pass


def _combo_safe(w) -> bool:
    """Translate a combo's items only when the program reads values from item data
    (or the combo opts in), so code that reads currentText() keeps English values."""
    if w.property("pf_i18n"):
        return True
    return w.count() > 0 and all(w.itemData(i) is not None for i in range(w.count()))


def _swap_indexed(w, kind: str, i: int, getter, setter) -> None:
    key = f"_pf_en_{kind}s"
    origs = list(w.property(key) or [])
    while len(origs) <= i:
        origs.append("")
    cur = getter(i)
    if not origs[i] or (cur != origs[i] and cur != lookup(origs[i])):
        origs[i] = cur
        w.setProperty(key, origs)
    want = lookup(origs[i]) if _LANG == "ar" else origs[i]
    if want != cur:
        setter(i, want)


_ITEM_ROLE = 0x0100 + 900          # Qt.UserRole + 900 keeps the English text of an item


def _swap_item(item, col: int) -> None:
    role = _ITEM_ROLE + col
    cur = item.text(col) if hasattr(item, "columnCount") else item.text()
    orig = item.data(col, role) if hasattr(item, "columnCount") else item.data(role)
    if not orig or (cur != orig and cur != lookup(orig)):
        orig = cur
        if hasattr(item, "columnCount"):
            item.setData(col, role, orig)
        else:
            item.setData(role, orig)
    want = lookup(orig) if _LANG == "ar" else orig
    if want != cur:
        if hasattr(item, "columnCount"):
            item.setText(col, want)
        else:
            item.setText(want)


def translate_actions(actions) -> None:
    for a in actions:
        if a.isSeparator():
            continue
        if a.property("pf_user"):
            continue
        _swap(a, "text", a.text, a.setText)
        if a.toolTip() and a.toolTip() != a.text():
            _swap(a, "toolTip", a.toolTip, a.setToolTip)
        if a.menu() is not None:
            translate_actions(a.menu().actions())


def translate_tree(root) -> None:
    from PySide6.QtWidgets import QWidget
    translate_widget(root)
    for w in root.findChildren(QWidget):
        translate_widget(w)


_FILTER = None


def install(app, lang: str | None = None) -> None:
    """Install the automatic translator once and apply the current language."""
    global _FILTER
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtWidgets import QMenu, QWidget
    if lang is not None:
        set_language(lang)
    if _FILTER is None:
        class _Translator(QObject):
            def eventFilter(self, obj, ev):  # noqa: N802
                t = ev.type()
                if t == QEvent.Polish and isinstance(obj, QWidget):
                    translate_widget(obj)
                elif t == QEvent.Show and isinstance(obj, QWidget) and (obj.isWindow() or isinstance(obj, QMenu)):
                    translate_tree(obj)
                return False
        _FILTER = _Translator(app)
        app.installEventFilter(_FILTER)
    app.setLayoutDirection(Qt.RightToLeft if is_rtl() else Qt.LeftToRight)
    retranslate_all(app)


def retranslate_all(app) -> None:
    for w in app.topLevelWidgets():
        translate_tree(w)
