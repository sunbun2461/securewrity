"""Dates for @-mentions: understand what people type after "@", and how a date is shown.

parse_date("next friday", today) → date. Understands:
  today · tomorrow · yesterday · now
  monday … sunday, "next friday", "last tuesday", "this thursday"   (also mon, tue, tues, …)
  "in 3 days", "in 2 weeks", "in 1 month", "3 days ago", "2 weeks ago"
  "next week", "last week", "next month", "next year"
  "nov 12", "november 12", "12 nov", "nov 12 2026", "nov 12, 2026", "12th november"
  2026-11-12 · 11/12 · 11/12/2026 · 11/12/26 · 11-12-2026     (US order: month first)
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
WEEKDAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}
WEEKDAYS.update({d.lower(): i for i, d in enumerate(calendar.day_abbr)})
WEEKDAYS.update({"tues": 1, "wednes": 2, "thur": 3, "thurs": 3, "weds": 2})
NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def label(d: date) -> str:
    """How a date mention reads on the page: 'November 12, 2026'."""
    return f"{calendar.month_name[d.month]} {d.day}, {d.year}"


def relative_hint(d: date, today: date | None = None) -> str:
    today = today or date.today()
    n = (d - today).days
    if n == 0:
        return "Today"
    if n == 1:
        return "Tomorrow"
    if n == -1:
        return "Yesterday"
    day = calendar.day_name[d.weekday()]
    weeks = (d - timedelta(days=d.weekday()) - (today - timedelta(days=today.weekday()))).days // 7
    if weeks == 0:
        return f"This {day}"
    if weeks == 1:
        return f"Next {day}"
    if weeks == -1:
        return f"Last {day}"
    return f"{day}, in {n} days" if n > 0 else f"{day}, {-n} days ago"


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _make(y, m, d) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _year(y: str | None, today: date) -> int:
    if not y:
        return today.year
    y = int(y)
    return y + 2000 if y < 100 else y


def parse_date(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    t = re.sub(r"[,.]", " ", text.strip().lower())
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return None
    if t in ("today", "now", "tod"):
        return today
    if t in ("tomorrow", "tmrw", "tmr", "tomorow"):
        return today + timedelta(days=1)
    if t == "yesterday":
        return today - timedelta(days=1)

    # weekdays: "friday", "next friday", "last friday", "this friday"
    m = re.fullmatch(r"(next |last |this |coming |on )?([a-z]+)", t)
    if m and m.group(2) in WEEKDAYS:
        want = WEEKDAYS[m.group(2)]
        word = (m.group(1) or "").strip()
        if word == "last":
            back = (today.weekday() - want) % 7 or 7
            return today - timedelta(days=back)
        ahead = (want - today.weekday()) % 7
        if word == "next":  # "next friday" on a Tuesday = Friday of next week
            ahead = ahead or 7
            if today.weekday() + ahead <= 6:
                ahead += 7
            return today + timedelta(days=ahead)
        return today + timedelta(days=ahead)  # "friday" / "this friday": the coming one (today if it's today)

    # "next week" / "last month" / "next year"
    m = re.fullmatch(r"(next|last) (week|month|year)", t)
    if m:
        s = 1 if m.group(1) == "next" else -1
        if m.group(2) == "week":
            return today + timedelta(weeks=s)
        return _add_months(today, s * (1 if m.group(2) == "month" else 12))

    # "in 3 days" / "3 days ago" / "in a week"
    m = re.fullmatch(r"(?:in )?(\d+|[a-z]+) (day|days|week|weeks|month|months|year|years)( ago| from now)?", t)
    if m and (m.group(1).isdigit() or m.group(1) in NUMBERS) and (t.startswith("in ") or m.group(3)):
        n = int(m.group(1)) if m.group(1).isdigit() else NUMBERS[m.group(1)]
        if m.group(3) == " ago":
            n = -n
        unit = m.group(2).rstrip("s")
        if unit == "day":
            return today + timedelta(days=n)
        if unit == "week":
            return today + timedelta(weeks=n)
        return _add_months(today, n * (1 if unit == "month" else 12))

    # 2026-11-12
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", t)
    if m:
        return _make(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # 11/12, 11/12/2026, 11-12-26 (month first)
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2}|\d{4}))?", t)
    if m:
        return _make(_year(m.group(3), today), int(m.group(1)), int(m.group(2)))

    # "nov 12", "november 12 2026", "nov 12th"
    m = re.fullmatch(r"([a-z]+) (\d{1,2})(?:st|nd|rd|th)?(?: (\d{2}|\d{4}))?", t)
    if m and m.group(1) in MONTHS:
        return _make(_year(m.group(3), today), MONTHS[m.group(1)], int(m.group(2)))
    # "12 nov", "12th of november 2026"
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? (?:of )?([a-z]+)(?: (\d{2}|\d{4}))?", t)
    if m and m.group(2) in MONTHS:
        return _make(_year(m.group(3), today), MONTHS[m.group(2)], int(m.group(1)))
    # "november" / "nov 2026" → the 1st
    m = re.fullmatch(r"([a-z]+)(?: (\d{4}))?", t)
    if m and m.group(1) in MONTHS and len(m.group(1)) >= 3:
        return _make(_year(m.group(2), today), MONTHS[m.group(1)], 1)
    return None
