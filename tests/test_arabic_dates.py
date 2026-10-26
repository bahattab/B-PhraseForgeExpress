"""Arabic dates in macros: Hijri (tabular) calendar, Arabic month names, Arabic-Indic digits."""
import random
from datetime import date, datetime

from phraseforge.host import ExpansionContext
from phraseforge.macros import MacroEngine
from phraseforge.macros.datetimes import format_dt, to_hijri
from tests.fakehost import FakeHost

NOW = datetime(2024, 3, 11, 9, 30)      # 1 Ramadan 1445


def T(s, settings=None):
    host = FakeHost()
    host.settings.update(settings or {})
    eng = MacroEngine(host, clock=lambda: NOW, rng=random.Random(1))
    return eng.expand_to_text(s, ExpansionContext())


def test_tabular_hijri_known_dates():
    # first days of Ramadan 1444-1446 and the epoch
    assert to_hijri(date(2023, 3, 23)) == (1444, 9, 1)
    assert to_hijri(date(2024, 3, 11)) == (1445, 9, 1)
    assert to_hijri(date(2025, 3, 1)) == (1446, 9, 1)
    assert to_hijri(date(622, 7, 19)) == (1, 1, 1)


def test_format_hijri_arabic_digits():
    assert format_dt(NOW, "d MMMM yyyy", "ar", "hijri") == "1 رمضان 1445"
    assert format_dt(NOW, "dd/MM/yyyy", "en", "hijri", "arabic") == "٠١/٠٩/١٤٤٥"
    assert format_dt(NOW, "dddd d MMMM yyyy tt", "ar") == "الاثنين 11 مارس 2024 ص"
    assert format_dt(NOW, "MMMM", "en", "hijri") == "Ramadan"


def test_date_macro_options():
    assert T('{#date -format "d MMMM yyyy" -lang ar -calendar hijri}') == "1 رمضان 1445"
    assert T('{#date -format "yyyy" -digits arabic}') == "٢٠٢٤"
    assert T('{#date -format "dd.MM.yyyy"}') == "11.03.2024"
    # defaults from Settings > Display > Dates in phrases
    assert T('{#date -format "d MMMM"}', {"date.lang": "ar", "date.calendar": "hijri", "date.digits": "arabic"}) == "١ رمضان"
