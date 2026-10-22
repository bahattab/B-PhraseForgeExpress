"""Tiny translation helper. English strings are the keys; Arabic table below."""
from __future__ import annotations

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


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang or "en"


def language() -> str:
    return _LANG


def tr(text: str) -> str:
    if _LANG == "ar":
        return AR.get(text, text)
    return text
