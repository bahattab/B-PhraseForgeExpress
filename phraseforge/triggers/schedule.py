"""Time-trigger schedules (PRD FR-TRG-07 and the "random delay" of G-10).

A time trigger's value is the time followed by options, so older values keep working:

    08:30                                   every day at 08:30
    every:15                                every 15 minutes
    08:30 days=mon,tue,fri                  only on these weekdays
    08:30 from=2026-11-01 to=2026-12-31     only between these dates (both included)
    08:30 once                              once only, on the first day it is due
    08:30 random=10                         at a random moment up to 10 minutes later

Options can be combined in any order. format() writes them back in this order.
"""
from __future__ import annotations

import random as _random
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class Schedule:
    kind: str = "daily"              # daily | every
    minutes: int = 0                 # daily: minute of the day; every: interval
    days: frozenset[int] = field(default_factory=frozenset)   # 0 = Monday; empty = every day
    start: date | None = None
    end: date | None = None
    once: bool = False
    random_minutes: int = 0

    @property
    def time_text(self) -> str:
        return f"every:{self.minutes}" if self.kind == "every" else f"{self.minutes // 60:02d}:{self.minutes % 60:02d}"

    def with_time(self, hhmm: str) -> "Schedule":
        k, n = _parse_time(hhmm)
        return replace(self, kind=k, minutes=n)

    def day_allowed(self, d: date) -> bool:
        if self.days and d.weekday() not in self.days:
            return False
        if self.start and d < self.start:
            return False
        if self.end and d > self.end:
            return False
        return True

    def next_run(self, now: datetime, last: datetime | None = None, done: bool = False) -> datetime | None:
        """When it fires next (without the random delay); None = never again."""
        if done and self.once:
            return None
        if self.kind == "every":
            t = (last + timedelta(minutes=self.minutes)) if last else now
            t = max(t, now).replace(second=0, microsecond=0)
            for _ in range(366 * 2):
                if self.day_allowed(t.date()):
                    return t
                if self.end and t.date() > self.end:
                    return None
                t = datetime.combine(t.date() + timedelta(days=1), datetime.min.time())
            return None
        d = now.date()
        at = datetime.combine(d, datetime.min.time()) + timedelta(minutes=self.minutes)
        if at < now.replace(second=0, microsecond=0) or (last is not None and last.date() == d):
            d += timedelta(days=1)
        for _ in range(366 * 8):
            if self.end and d > self.end:
                return None
            if self.day_allowed(d):
                return datetime.combine(d, datetime.min.time()) + timedelta(minutes=self.minutes)
            d += timedelta(days=1)
        return None

    def describe(self) -> str:
        parts = [f"every {self.minutes} min" if self.kind == "every" else f"at {self.time_text}"]
        if self.days:
            parts.append(", ".join(DAYS[i].capitalize() for i in sorted(self.days)))
        if self.start or self.end:
            parts.append(f"{self.start or '…'} to {self.end or '…'}")
        if self.random_minutes:
            parts.append(f"up to {self.random_minutes} min later")
        if self.once:
            parts.append("once")
        return "; ".join(parts)


def _parse_time(v: str) -> tuple[str, int]:
    v = v.strip().lower()
    if v.startswith("every:"):
        n = int(v.split(":", 1)[1])
        if n <= 0:
            raise ValueError("interval must be positive")
        return "every", n
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", v)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"bad time trigger {v!r}")
    return "daily", int(m.group(1)) * 60 + int(m.group(2))


def parse(value: str) -> Schedule:
    """Raises ValueError for anything it does not understand."""
    words = (value or "").split()
    if not words:
        raise ValueError("empty time trigger")
    kind, n = _parse_time(words[0])
    s = Schedule(kind, n)
    for w in words[1:]:
        key, eq, arg = w.lower().partition("=")
        if key == "once" and not eq:
            s.once = True
        elif key == "days" and arg:
            try:
                s.days = frozenset(DAYS.index(d[:3]) for d in arg.split(",") if d)
            except ValueError:
                raise ValueError(f"bad weekday in {w!r}") from None
        elif key in ("from", "to") and arg:
            d = date.fromisoformat(arg)
            if key == "from":
                s.start = d
            else:
                s.end = d
        elif key == "random" and arg.isdigit():
            s.random_minutes = min(int(arg), 24 * 60)
        else:
            raise ValueError(f"unknown time trigger option {w!r}")
    if s.start and s.end and s.start > s.end:
        raise ValueError("the start date is after the end date")
    return s


def format(s: Schedule) -> str:  # noqa: A001 - mirrors parse()
    out = [s.time_text]
    if s.days:
        out.append("days=" + ",".join(DAYS[i] for i in sorted(s.days)))
    if s.start:
        out.append(f"from={s.start.isoformat()}")
    if s.end:
        out.append(f"to={s.end.isoformat()}")
    if s.random_minutes:
        out.append(f"random={s.random_minutes}")
    if s.once:
        out.append("once")
    return " ".join(out)


class Runner:
    """Decides, minute by minute, which schedules fire. State is kept per key (one trigger)."""

    def __init__(self, rng: _random.Random | None = None):
        self._rng = rng or _random.Random()
        self.last: dict = {}          # key -> datetime it last fired (or, for every:, started)
        self.pending: dict = {}       # key -> datetime a randomly delayed run is due
        self.done: set = set()        # keys of "once" schedules that already ran

    def due(self, key, s: Schedule, now: datetime) -> bool:
        if key in self.done:
            return False
        now = now.replace(second=0, microsecond=0)
        if key in self.pending:
            if now >= self.pending[key]:
                del self.pending[key]
                return self._fired(key, s)
            return False
        if not self.day_allowed_now(s, now):
            return False
        if s.kind == "daily":
            last = self.last.get(key)
            if now.hour * 60 + now.minute != s.minutes or (last is not None and last.date() == now.date()):
                return False
        else:
            last = self.last.get(key)
            if last is None:
                self.last[key] = now
                return False
            if (now - last).total_seconds() < s.minutes * 60:
                return False
        self.last[key] = now
        if s.random_minutes:
            self.pending[key] = now + timedelta(minutes=self._rng.randint(0, s.random_minutes))
            if self.pending[key] > now:
                return False
            del self.pending[key]
        return self._fired(key, s)

    @staticmethod
    def day_allowed_now(s: Schedule, now: datetime) -> bool:
        return s.day_allowed(now.date())

    def _fired(self, key, s: Schedule) -> bool:
        if s.once:
            self.done.add(key)
        return True
