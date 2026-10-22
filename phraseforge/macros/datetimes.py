"""Date formatting and offset arithmetic for date/time macros.

Format tokens (case matters, like .NET):
  yyyy yy  MMMM MMM MM M  dddd ddd dd d  HH H hh h  mm m  ss s  tt
  DDD (day of year, 001-366)  zzz (UTC offset, +03:00)
  'quoted text' is literal. A format containing '%' is passed to strftime.
Offset units: y, M/m/mo (month), w, d, wd (workday), h, min/n (minute), s.
  Example: "+3d", "-2h", "+1m", "+10wd +30min".
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"],
    "ar": ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
           "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
           "September", "Oktober", "November", "Dezember"],
}
DAYS = {  # Monday first
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "ar": ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"],
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
}
_DAY_KEYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_FMT = re.compile(r"'[^']*'|yyyy|yy|MMMM|MMM|MM|M|DDD|dddd|ddd|dd|d|HH|H|hh|h|mm|m|ss|s|tt|zzz")


def _tz(dt: datetime) -> str:
    off = dt.utcoffset() if dt.tzinfo else dt.astimezone().utcoffset()
    mins = int(off.total_seconds() // 60) if off is not None else 0
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return f"{sign}{mins // 60:02d}:{mins % 60:02d}"
_OFF = re.compile(r"([+-]?)\s*(\d+)\s*(wd|min|mo|y|m|w|d|h|n|s)", re.I)


def format_dt(dt: datetime, fmt: str, lang: str = "en") -> str:
    if "%" in fmt:
        return dt.strftime(fmt)
    months = MONTHS.get(lang, MONTHS["en"])
    days = DAYS.get(lang, DAYS["en"])

    def rep(m: re.Match) -> str:
        t = m.group(0)
        if t.startswith("'"):
            return t[1:-1]
        h12 = dt.hour % 12 or 12
        if t == "zzz":
            return _tz(dt)
        if t == "DDD":
            return f"{dt.timetuple().tm_yday:03d}"
        return {
            "yyyy": f"{dt.year:04d}", "yy": f"{dt.year % 100:02d}",
            "MMMM": months[dt.month - 1], "MMM": months[dt.month - 1][:3] if lang == "en" or lang == "de" else months[dt.month - 1],
            "MM": f"{dt.month:02d}", "M": str(dt.month),
            "dddd": days[dt.weekday()], "ddd": days[dt.weekday()][:3] if lang != "ar" else days[dt.weekday()],
            "dd": f"{dt.day:02d}", "d": str(dt.day),
            "HH": f"{dt.hour:02d}", "H": str(dt.hour), "hh": f"{h12:02d}", "h": str(h12),
            "mm": f"{dt.minute:02d}", "m": str(dt.minute), "ss": f"{dt.second:02d}", "s": str(dt.second),
            "tt": "AM" if dt.hour < 12 else "PM",
        }[t]

    return _FMT.sub(rep, fmt)


def add_months(dt: datetime, n: int) -> datetime:
    y, mo = divmod(dt.month - 1 + n, 12)
    year, month = dt.year + y, mo + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def weekend_days(spec: str) -> set[int]:
    out = {_DAY_KEYS[p.strip()[:3].lower()] for p in spec.split(",") if p.strip()[:3].lower() in _DAY_KEYS}
    return out


def add_workdays(dt: datetime, n: int, weekend: set[int]) -> datetime:
    if len(weekend) >= 7:
        return dt
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        dt += timedelta(days=step)
        if dt.weekday() not in weekend:
            left -= 1
    return dt


def apply_offset(dt: datetime, spec: str, weekend: set[int] | None = None) -> datetime:
    if not spec:
        return dt
    weekend = {5, 6} if weekend is None else weekend
    matched = False
    for sign, num, unit in _OFF.findall(spec):
        matched = True
        n = int(num) * (-1 if sign == "-" else 1)
        u = unit.lower()
        if u == "y":
            dt = add_months(dt, 12 * n)
        elif u in ("m", "mo"):
            dt = add_months(dt, n)
        elif u == "w":
            dt += timedelta(weeks=n)
        elif u == "d":
            dt += timedelta(days=n)
        elif u == "wd":
            dt = add_workdays(dt, n, weekend)
        elif u == "h":
            dt += timedelta(hours=n)
        elif u in ("min", "n"):
            dt += timedelta(minutes=n)
        elif u == "s":
            dt += timedelta(seconds=n)
    if not matched:
        raise ValueError(f"bad offset '{spec}'")
    return dt


def parse_date(text: str, now: datetime) -> datetime:
    t = text.strip()
    if not t or t.lower() in ("now", "today"):
        return now if t.lower() != "today" else now.replace(hour=0, minute=0, second=0, microsecond=0)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            pass
    raise ValueError(f"cannot parse date '{text}'")


def parse_time(text: str, now: datetime) -> datetime:
    t = text.strip()
    if not t or t.lower() == "now":
        return now
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            tm = datetime.strptime(t.upper() if "M" in t.upper() else t, fmt)
            return now.replace(hour=tm.hour, minute=tm.minute, second=tm.second, microsecond=0)
        except ValueError:
            pass
    raise ValueError(f"cannot parse time '{text}'")


def workdays_between(a: date, b: date, weekend: set[int]) -> int:
    sign = 1
    if b < a:
        a, b, sign = b, a, -1
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() not in weekend:
            n += 1
    return n * sign
