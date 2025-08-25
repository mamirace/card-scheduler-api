# card_scheduler_tr.py
# Deterministic credit-card usage sequencing per bespoke business rules.
# Türkiye sürümü (ülke parametresi yok, tatiller sabit).
# Python 3.10+

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict

# ---------------------- Türkiye Defaults ----------------------

TURKEY_TZ = ZoneInfo("Europe/Istanbul")
WEEKENDS = (5, 6)  # Cumartesi, Pazar
DEFAULT_GRACE = 10

# Month names for formatting (short form)
MONTH_NAMES_TR = ["Oca","Şub","Mar","Nis","May","Haz","Tem","Ağu","Eyl","Eki","Kas","Ara"]
MONTH_NAMES_EN = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

@dataclass
class CardInput:
    card_name: str
    statement_closing_day: Optional[int]  # 1..31 or None
    payment_due_day: Optional[int]        # 1..31 or None
    grace_period: Optional[int]           # days or None

@dataclass
class CardComputed:
    card: CardInput
    closing: date
    payment: date

# ---------------------- Tatiller ----------------------

def _turkey_holidays(year: int) -> set[date]:
    """Her yıl için sabit tatil günlerini döndürür."""
    holidays: set[date] = set()

    # Resmî tatiller (her yıl)
    holidays.add(date(year, 1, 1))   # 1 Ocak
    holidays.add(date(year, 4, 23))  # 23 Nisan
    holidays.add(date(year, 5, 1))   # 1 Mayıs
    holidays.add(date(year, 5, 19))  # 19 Mayıs
    holidays.add(date(year, 7, 15))  # 15 Temmuz
    holidays.add(date(year, 8, 30))  # 30 Ağustos
    holidays.add(date(year, 10, 29)) # 29 Ekim

    # Dini tatiller (manuel girildi)
    if year == 2026:
        # 20–22 Mart 2026
        for d in range(20, 23):
            holidays.add(date(2026, 3, d))
        # 27–30 Mayıs 2026
        for d in range(27, 31):
            holidays.add(date(2026, 5, d))

    return holidays

# ---------------------- Yardımcı Fonksiyonlar ----------------------

def _is_business_day(d: date) -> bool:
    if d.weekday() in WEEKENDS:
        return False
    if d in _turkey_holidays(d.year):
        return False
    return True

def _next_business_day_on_or_after(d: date) -> date:
    cur = d
    while not _is_business_day(cur):
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

def _compute_closing_payment_for_month(y: int, m: int, card: CardInput) -> CardComputed:
    grace = card.grace_period if card.grace_period is not None else DEFAULT_GRACE

    if card.statement_closing_day is not None:
        closing = _mk_date_from_day(y, m, card.statement_closing_day)
        payment_raw = closing + timedelta(days=grace)
        payment = _next_business_day_on_or_after(payment_raw)
    elif card.payment_due_day is not None:
        payment_raw = _mk_date_from_day(y, m, card.payment_due_day)
        closing = payment_raw - timedelta(days=grace)
        payment = _next_business_day_on_or_after(payment_raw)
    else:
        raise ValueError(f"Card {card.card_name}: either closing day or payment day must be provided.")

    return CardComputed(card=card, closing=closing, payment=payment)

def _advance_if_past(today: date, comp: CardComputed) -> CardComputed:
    y, m = comp.closing.year, comp.closing.month
    card = comp.card
    while comp.closing < today:
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
        comp = _compute_closing_payment_for_month(y, m, card)
    return comp

def _all_current_pairs(today: date, cards: List[CardInput]) -> List[CardComputed]:
    pairs = []
    for c in cards:
        y, m = today.year, today.month
        comp = _compute_closing_payment_for_month(y, m, c)
        comp = _advance_if_past(today, comp)
        pairs.append(comp)
    return pairs

def _pick_first_row(pairs: List[CardComputed]) -> List[CardComputed]:
    if not pairs:
        return []
    max_pay = max(p.payment for p in pairs)
    candidates = [p for p in pairs if p.payment == max_pay]
    return candidates

def _nearest_other_closing_after(pairs: List[CardComputed], excluding_cards: List[str], start_inclusive: date) -> Optional[date]:
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

# ---------------------- Ana Fonksiyon ----------------------

def schedule_cards(cards: List[CardInput],
                   system_dt: Optional[datetime] = None,
                   language: str = "tr") -> List[Dict]:
    """
    Returns list of rows (dict) with keys:
      Kart Adı | Beklenen Kesim | Kullanım | Kesim | Ödeme
    Number of rows = len(cards) + 1 (per spec).
    """
    if not cards or len(cards) < 1:
        return []

    if system_dt is None:
        base_dt = datetime.now(timezone.utc).astimezone(TURKEY_TZ)
    else:
        base_dt = system_dt.astimezone(TURKEY_TZ)

    today_local = base_dt.date()
    per_card_pairs: Dict[str, CardComputed] = {}
    for c in cards:
        comp0 = _compute_closing_payment_for_month(today_local.year, today_local.month, c)
        comp = _advance_if_past(today_local, comp0)
        per_card_pairs[c.card_name] = comp

    pairs = list(per_card_pairs.values())
    rows: List[Dict] = []

    # 1st row selection
    first_row_cards = _pick_first_row(pairs)
    selected_names = [p.card.card_name for p in first_row_cards]

    begins: List[date] = [today_local]
    begin = min(begins) if begins else today_local

    nearest_other = _nearest_other_closing_after(pairs, excluding_cards=selected_names, start_inclusive=begin)
    end = nearest_other if nearest_other else begin

    def next_own_closing_after(cpair: CardComputed, start_after_inclusive: date) -> CardComputed:
        y, m = cpair.closing.year, cpair.closing.month
        card = cpair.card
        comp = cpair
        while comp.closing < start_after_inclusive:
            if m == 12:
                y, m = y + 1, 1
            else:
                m += 1
            comp = _compute_closing_payment_for_month(y, m, card)
        return comp

    def prev_own_closing_before(cpair: CardComputed, start_exclusive: date) -> Optional[date]:
        after = next_own_closing_after(cpair, start_exclusive)
        y, m = after.closing.year, after.closing.month
        
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
        prev = _compute_closing_payment_for_month(y, m, cpair.card)
        return prev.closing

    def add_row(
        picks: List[CardComputed],
        begin: date,
        end: date,
        is_first: bool,
        number_override: Optional[int] = None,
    ):
        if is_first:
            for p in picks:
                after = next_own_closing_after(p, end + timedelta(days=1))
                closing_for_use = after.closing
                payment_for_use = after.payment
                row = {
                    "Kart Adı": p.card.card_name,
                    "Beklenen Kesim": "",
                    "Kullanım": f"{_fmt(begin, language)} – {_fmt(end, language)}",
                    "Kesim": _fmt(closing_for_use, language),
                    "Ödeme": _fmt(payment_for_use, language),
                }
                rows.append(row)
        else:
            groups = _group_by_use_date(picks)
            for group in groups:
                after = next_own_closing_after(group[0], end + timedelta(days=1))
                closing_for_use = after.closing
                payment_for_use = after.payment
                row = {
                    "Kart Adı": ", ".join([p.card.card_name for p in group]),
                    "Beklenen Kesim": _fmt(prev_own_closing_before(group[0], begin), language),
                    "Kullanım": f"{_fmt(begin, language)} – {_fmt(end, language)}",
                    "Kesim": _fmt(closing_for_use, language),
                    "Ödeme": _fmt(payment_for_use, language),
                }
                rows.append(row)

    add_row(first_row_cards, begin, end, is_first=True, number_override=1)

    used_rows = 1
    max_rows = len(cards) + 1
    prev_row_begin = begin
    prev_row_end = end

    while used_rows < max_rows:
        candidates = []
        for p in pairs:
            after_for_selection = next_own_closing_after(p, prev_row_begin)
            candidates.append((after_for_selection.closing, after_for_selection.payment, p))

        if not candidates:
            break

        min_closing = min(c[0] for c in candidates)
        near = [c for c in candidates if c[0] == min_closing]
        max_payment = max(c[1] for c in near)
        picks = [c[2] for c in near if c[1] == max_payment]

        row_begin = prev_row_end + timedelta(days=1)
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
