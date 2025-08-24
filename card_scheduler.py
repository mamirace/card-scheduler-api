
# card_scheduler.py
# Deterministic credit-card usage sequencing per bespoke business rules.
# Stdlib-only; Python 3.10+.
#
# HOW TO USE (inside Code Interpreter / local Python):
#   from card_scheduler import schedule_cards, CardInput
#   cards = [
#     CardInput(card_name="X Card", statement_closing_day=3, payment_due_day=None, grace_period=21, country="USA"),
#     CardInput(card_name="Y Card", statement_closing_day=None, payment_due_day=10, grace_period=25, country="USA"),
#   ]
#   result = schedule_cards(cards, system_dt=None, holidays_csv=None, language="tr")
#   # result is a list[dict] rows already formatted for display.
#
# Optional holiday support:
#   Provide holidays_csv="holidays.csv" with columns: country,date
#   Example rows:
#     USA,2025-09-01   # Labor Day
#     Türkiye,2025-10-29
#
# Notes:
# - National/federal/bank holidays: supplied by CSV (so you can maintain accuracy).
# - Weekends differ by country (see WEEKENDS).
# - Multi-timezone countries default tz: see DEFAULT_TZ.
# - If grace not provided, defaults by country: see DEFAULT_GRACE.
# - Output dates omit year and are formatted in target language (tr/en).

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
import csv
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict, Tuple

# ---------------------- Country Defaults ----------------------

DEFAULT_TZ: Dict[str, str] = {
    "USA": "America/New_York",
    "United States": "America/New_York",
    "United Kingdom": "Europe/London",
    "UK": "Europe/London",
    "Canada": "America/New_York",
    "Brazil": "America/Sao_Paulo",
    "Brasil": "America/Sao_Paulo",
    "Mexico": "America/Mexico_City",
    "Australia": "Australia/Sydney",
    "Russia": "Europe/Moscow",
    "Chile": "America/Santiago",
    "Indonesia": "Asia/Jakarta",
    "Türkiye": "Europe/Istanbul",
    "Turkey": "Europe/Istanbul",
}

# Weekend days per ISO: Monday=0 ... Sunday=6
WEEKENDS: Dict[str, Tuple[int, int]] = {
    # Most countries
    "default": (5, 6),  # Saturday, Sunday
    # Add exceptions here if needed (e.g., some Middle East countries Fri/Sat or Sat/Sun changes)
    # "UAE": (4, 5),  # Friday, Saturday (example legacy)
}

DEFAULT_GRACE: Dict[str, int] = {
    "USA": 21,
    "United States": 21,
    "Canada": 21,
    "United Kingdom": 21,
    "UK": 21,
    "Brazil": 21,
    "Brasil": 21,
    "Türkiye": 10,
    "Turkey": 10,
    "_other": 20,
}

# Month names for formatting (short form)
MONTH_NAMES_TR = ["Oca","Şub","Mar","Nis","May","Haz","Tem","Ağu","Eyl","Eki","Kas","Ara"]
MONTH_NAMES_EN = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

@dataclass
class CardInput:
    card_name: str
    statement_closing_day: Optional[int]  # 1..31 or None
    payment_due_day: Optional[int]        # 1..31 or None
    grace_period: Optional[int]           # days or None
    country: Optional[str]                # e.g., "USA", "Türkiye"

@dataclass
class CardComputed:
    card: CardInput
    closing: date
    payment: date


def _normalize_country(c: Optional[str]) -> Optional[str]:
    if not c:
        return None
    return c.strip()


def _country_tz(country: Optional[str], device_tz: Optional[str]) -> ZoneInfo:
    if country and country in DEFAULT_TZ:
        return ZoneInfo(DEFAULT_TZ[country])
    # Fallback to device tz if provided, otherwise UTC
    try:
        if device_tz:
            return ZoneInfo(device_tz)
    except Exception:
        pass
    return ZoneInfo("UTC")


def _country_weekend(country: Optional[str]) -> Tuple[int, int]:
    # Could extend with per-country weekend exceptions
    return WEEKENDS.get(country or "", WEEKENDS["default"])


def _country_grace(country: Optional[str]) -> int:
    if country and country in DEFAULT_GRACE:
        return DEFAULT_GRACE[country]
    return DEFAULT_GRACE["_other"]


def _read_holidays(holidays_csv: Optional[str]) -> Dict[str, set]:
    days: Dict[str, set] = {}
    if not holidays_csv:
        return days
    try:
        with open(holidays_csv, newline="", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                c = _normalize_country(row.get("country"))
                d = row.get("date")
                if not c or not d:
                    continue
                y, m, dd = [int(x) for x in d.split("-")]
                days.setdefault(c, set()).add(date(y, m, dd))
    except Exception:
        # Fail silently; no holidays loaded
        pass
    return days


def _is_business_day(d: date, country: Optional[str], holidays: Dict[str, set]) -> bool:
    wknd = _country_weekend(country)
    if d.weekday() in wknd:
        return False
    if country and country in holidays and d in holidays[country]:
        return False
    # Also, if country not in holidays but there is a "_GLOBAL" entry, apply it
    if "_GLOBAL" in holidays and d in holidays["_GLOBAL"]:
        return False
    return True


def _next_business_day_on_or_after(d: date, country: Optional[str], holidays: Dict[str, set]) -> date:
    cur = d
    while not _is_business_day(cur, country, holidays):
        cur += timedelta(days=1)
    return cur


def _days_in_month(y: int, m: int) -> int:
    if m == 12:
        nxt = date(y+1, 1, 1)
    else:
        nxt = date(y, m+1, 1)
    return (nxt - timedelta(days=1)).day


def _mk_date_from_day(y: int, m: int, day: int) -> date:
    dim = _days_in_month(y, m)
    d = min(day, dim)
    return date(y, m, d)


def _format_day_tr(d: date) -> str:
    return f"{d.day} {MONTH_NAMES_TR[d.month-1]}"


def _format_day_en(d: date) -> str:
    return f"{d.day} {MONTH_NAMES_EN[d.month-1]}"


def _fmt(d: date, language: str) -> str:
    if language.lower().startswith("tr"):
        return _format_day_tr(d)
    return _format_day_en(d)


def _compute_closing_payment_for_month(y: int, m: int, card: CardInput, holidays: Dict[str, set]) -> CardComputed:
    country = _normalize_country(card.country)
    grace = card.grace_period if card.grace_period is not None else _country_grace(country)

    if card.statement_closing_day is not None:
        closing = _mk_date_from_day(y, m, card.statement_closing_day)
        # Payment = Closing + Grace, then push to next business day if needed
        payment_raw = closing + timedelta(days=grace)
        payment = _next_business_day_on_or_after(payment_raw, country, holidays)
    elif card.payment_due_day is not None:
        payment_raw = _mk_date_from_day(y, m, card.payment_due_day)
        # Even if raw payment falls on holiday, for Closing computation we use payment_raw unadjusted
        closing = payment_raw - timedelta(days=grace)
        # Real payment must be on a business day
        payment = _next_business_day_on_or_after(payment_raw, country, holidays)
    else:
        raise ValueError(f"Card {card.card_name}: either closing day or payment day must be provided.")

    return CardComputed(card=card, closing=closing, payment=payment)


def _advance_if_past(today: date, comp: CardComputed, holidays: Dict[str, set]) -> CardComputed:
    # If closing < today, eliminate pair and recompute for next month repeatedly until closing >= today
    y, m = comp.closing.year, comp.closing.month
    card = comp.card
    while comp.closing < today:
        # move to next month
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
        comp = _compute_closing_payment_for_month(y, m, card, holidays)
    return comp


def _all_current_pairs(today: date, cards: List[CardInput], holidays: Dict[str, set]) -> List[CardComputed]:
    pairs = []
    for c in cards:
        # compute pair for current month
        y, m = today.year, today.month
        comp = _compute_closing_payment_for_month(y, m, c, holidays)
        comp = _advance_if_past(today, comp, holidays)
        pairs.append(comp)
    return pairs


def _pick_first_row(pairs: List[CardComputed]) -> List[CardComputed]:
    # Choose card(s) with latest payment date
    if not pairs:
        return []
    max_pay = max(p.payment for p in pairs)
    candidates = [p for p in pairs if p.payment == max_pay]
    return candidates  # hepsi birlikte dönüyor

    # tie: pick those with minimum closing distance from "now" (they all share same payment)
    min_closing = min(p.closing for p in candidates)
    tied = [p for p in candidates if p.closing == min_closing]
    return tied  # can be >1 -> listed together


def _nearest_other_closing_after(pairs: List[CardComputed], excluding_cards: List[str], start_inclusive: date) -> Optional[date]:
    # Among cards not excluded, find the nearest closing >= start_inclusive
    others = [p.closing for p in pairs if p.card.card_name not in excluding_cards and p.closing >= start_inclusive]
    if not others:
        return None
    return min(others)

def _group_by_use_date(pairs: List[CardComputed]) -> List[List[CardComputed]]:
    grouped = []
    for p in pairs:
        added = False
        for group in grouped:
            if group[0].closing == p.closing and group[0].payment == p.payment:
                group.append(p)
                added = True
                break
        if not added:
            grouped.append([p])
    return grouped


def schedule_cards(cards: List[CardInput],
                   system_dt: Optional[datetime] = None,
                   holidays_csv: Optional[str] = None,
                   language: str = "tr",
                   device_tz: Optional[str] = None) -> List[Dict]:
    """
    Returns list of rows (dict) with keys:
      Raw Number, Card Name, Closing Waited, Use Date (Begin-End), Closing for Use, Payment for Use
    Number of rows = len(cards) + 1 (per spec).
    """
    if not cards or len(cards) < 1:
        return []

    # Eğer system_dt verilmemişse, bugünün tarihini yerel saatte alıyoruz.
    # İlk kartın ülkesine göre zaman dilimini belirliyoruz.
    country = _normalize_country(cards[0].country)
    tz = _country_tz(country, device_tz)
    
    # Eğer `system_dt` parametresi verilmemişse, bugünün tarihini UTC olarak alıp
    # yerel saat dilimine çeviriyoruz.
    if system_dt is None:
        base_dt = datetime.now(timezone.utc).astimezone(tz)
    else:
        base_dt = system_dt.astimezone(tz)

    # Tatil bilgilerini okuyoruz
    holidays = _read_holidays(holidays_csv)

    # Kartları güncel tarihe göre işliyoruz
    per_card_pairs: Dict[str, CardComputed] = {}
    for c in cards:
        country = _normalize_country(c.country)
        tz = _country_tz(country, device_tz)
        today_local = base_dt.date()  # Yerel tarih
        comp0 = _compute_closing_payment_for_month(today_local.year, today_local.month, c, holidays)
        comp = _advance_if_past(today_local, comp0, holidays)
        per_card_pairs[c.card_name] = comp

    pairs = list(per_card_pairs.values())

    rows: List[Dict] = []

    # 1st row selection
    first_row_cards = _pick_first_row(pairs)  # possibly multiple
    selected_names = [p.card.card_name for p in first_row_cards]

    # Determine use window for 1st row
    # Begin: system date (per spec) — we choose the earliest begin across the tied cards' countries
    # We'll show identical Begin-End for all cards in same row.
    begins: List[date] = []
    for p in first_row_cards:
        tz = _country_tz(_normalize_country(p.card.country), device_tz)
        begins.append(base_dt.astimezone(tz).date())
    begin = min(begins) if begins else base_dt.date()

    # End: nearest closing (inclusive) among OTHER cards (not in first row)
    nearest_other = _nearest_other_closing_after(pairs, excluding_cards=selected_names, start_inclusive=begin)
    end = nearest_other if nearest_other else begin  # if none, same-day window

    # Closing for Use / Payment for Use are for the card itself after the end (inclusive -> next own closing after end)
    def next_own_closing_after(cpair: CardComputed, start_after_inclusive: date) -> CardComputed:
        # walk months forward until closing >= start_after_inclusive
        y, m = cpair.closing.year, cpair.closing.month
        card = cpair.card
        comp = cpair
        while comp.closing < start_after_inclusive:
            if m == 12:
                y, m = y + 1, 1
            else:
                m += 1
            comp = _compute_closing_payment_for_month(y, m, card, holidays)
        return comp

    # Helper for Closing Waited (nearest past closing before the row's begin) for a given card
    def prev_own_closing_before(cpair: CardComputed, start_exclusive: date) -> Optional[date]:
        y, m = cpair.closing.year, cpair.closing.month
        card = cpair.card
        # Find the most recent closing < start_exclusive
        # Start from the month of cpair.closing and go backwards
        # Build a closing on (y,m) and move back while closing >= start_exclusive
        comp = _compute_closing_payment_for_month(y, m, card, holidays)
        while comp.closing >= start_exclusive:
            # move back a month
            if m == 1:
                y, m = y - 1, 12
            else:
                m -= 1
            comp = _compute_closing_payment_for_month(y, m, card, holidays)
        return comp.closing

    
    def add_row(
        picks: List[CardComputed],
        begin: date,
        end: date,
        is_first: bool,
        number_override: Optional[int] = None,
    ):
        # Eğer ilk sıra ise picks'teki tüm kartları ayrı ayrı yazacağız ama numarası aynı olacak
        if is_first:
            row_number = number_override if number_override is not None else (len(rows) + 1)
            for idx, p in enumerate(picks):
                after = next_own_closing_after(p, end + timedelta(days=1))
                closing_for_use = after.closing
                payment_for_use = after.payment
                row = {
                    "SIRA": row_number if idx == 0 else "",  # sadece ilkine sıra numarası yaz
                    "Kart Adı": p.card.card_name,
                    "Beklenen Kesim": "",  # ilk satırda boş bırakıyoruz
                    "Kullanım": f"{_fmt(begin, language)} – {_fmt(end, language)}",
                    "Closing": _fmt(closing_for_use, language),
                    "Payment": _fmt(payment_for_use, language),
                }
                rows.append(row)
        else:
            groups = _group_by_use_date(picks)
            for group in groups:
                after = next_own_closing_after(group[0], end + timedelta(days=1))
                closing_for_use = after.closing
                payment_for_use = after.payment
                row_number = number_override if number_override is not None else (len(rows) + 1)
                row = {
                    "SIRA": row_number,
                    "Kart Adı": ", ".join([p.card.card_name for p in group]),
                    "Beklenen Kesim": _fmt(prev_own_closing_before(group[0], begin), language),
                    "Kullanım": f"{_fmt(begin, language)} – {_fmt(end, language)}",
                    "Closing": _fmt(closing_for_use, language),
                    "Payment": _fmt(payment_for_use, language),
                }
                rows.append(row)




    add_row(first_row_cards, begin, end, is_first=True, number_override=1)


    # Next rows:
    # Selection anchor MUST be the PREVIOUS ROW'S BEGIN (spec).
    # But the next row's own begin date is previous row's END + 1.
    used_rows = 1
    max_rows = len(cards) + 1

    prev_row_begin = begin
    prev_row_end = end

    while used_rows < max_rows:
        # Select card(s) whose next closing is nearest to prev_row_begin (>= prev_row_begin allowed)
        candidates = []
        for p in pairs:
            # Find that card's closing for month so that closing >= prev_row_begin
            after_for_selection = next_own_closing_after(p, prev_row_begin)
            candidates.append((after_for_selection.closing, after_for_selection.payment, p))

        if not candidates:
            break

        min_closing = min(c[0] for c in candidates)
        near = [c for c in candidates if c[0] == min_closing]
        max_payment = max(c[1] for c in near)
        picks = [c[2] for c in near if c[1] == max_payment]

        # This row's own begin is previous row's end + 1
        row_begin = prev_row_end + timedelta(days=1)

        # Row end = nearest closing among ALL cards >= row_begin
        all_next_closings = []
        for p in pairs:
            nxt = next_own_closing_after(p, row_begin)
            all_next_closings.append(nxt.closing)
        row_end = min(all_next_closings) if all_next_closings else row_begin

        add_row(picks, row_begin, row_end, is_first=False)

        used_rows += 1
        prev_row_begin = row_begin
        prev_row_end = row_end

        if used_rows >= max_rows:
            break
    return rows
