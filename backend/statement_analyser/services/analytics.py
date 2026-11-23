"""Statement analytics: the numbers a lender or an analyst reads from a bank statement.

Pure functions: no database, nothing is changed. Every figure is a plain rule over the transactions (never a model's guess), and each detected
item carries the rows that caused it, so a person can check it. Money is returned as strings with two decimals.

  balances   average / monthly average / min / max end-of-day balance
  cash flow  credits, debits, net, volatility per month
  income     salary credits and how regular they are
  EMI / NACH recurring or mandate-style debits
  bounces    returned cheques / failed mandates and their charges
  cash       cash deposits (large ones flagged) and cash withdrawals
  circular   the same amount going out to and coming back from the same party within days
"""
import datetime as dt
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from statement_analyser.services.merchant_identifier import normalize_narration

TWO = Decimal("0.01")
LARGE_CASH = Decimal("50000")
CIRCULAR_MIN = Decimal("10000")
CIRCULAR_DAYS = 3

_SALARY = re.compile(r"\b(salary|sal|payroll|wages|stipend)\b", re.I)
_EMI = re.compile(r"\b(emi|nach|ach|ecs|loan|instalment|installment|mandate|si)\b", re.I)
_BOUNCE = re.compile(r"\b(bounce|bounced|dishonou?r(?:ed)?|returned?|ret|unpaid|insufficient|nsf|rtn)\b", re.I)
_BOUNCE_NEEDS = re.compile(r"\b(chq|cheque|check|ach|nach|ecs|mandate|emi|debit|ecs|funds|insufficient|unpaid)\b", re.I)
_CASH_IN = re.compile(r"\b(cash\s*dep(?:osit)?|cdm|by\s*cash|cash\s*deposit)\b", re.I)
_CASH_OUT = re.compile(r"\b(atm|cash\s*w(?:dl|ithdrawal)|nfs|cash\s*wdl)\b", re.I)
_GENERIC = {"upi", "neft", "imps", "rtgs", "transfer", "trf", "to", "from", "by", "payment", "pay", "ref", "bank", "ltd", "pvt", "the", "and",
            "dr", "cr", "txn", "ach", "nach", "ecs", "cash", "of", "in"}


@dataclass
class Row:
    idx: int
    date: Optional[dt.date]
    text: str
    credit: Decimal
    debit: Decimal
    balance: Optional[Decimal]

    @property
    def amount(self) -> Decimal:
        return self.credit or self.debit


def _d(v) -> Decimal:
    try:
        return Decimal(str(v)) if v not in (None, "") else Decimal(0)
    except Exception:  # noqa: BLE001
        return Decimal(0)


def money(v: Decimal) -> str:
    return str(Decimal(v).quantize(TWO))


def rows_from(transactions) -> list[Row]:
    """Accepts ReviewedTransaction / Transaction objects or dicts. Transaction fields may be plain values or ExtractedField."""
    out = []
    for i, t in enumerate(transactions):
        def get(name):
            v = t.get(name) if isinstance(t, dict) else getattr(t, name, None)
            return getattr(v, "value", v) if not isinstance(v, (str, int, float, Decimal, dt.date, type(None))) else v
        date = get("date")
        if isinstance(date, str):
            try:
                date = dt.date.fromisoformat(date)
            except ValueError:
                date = None
        bal = get("balance")
        out.append(Row(i + 1, date, str(get("description") or ""), _d(get("deposit")), _d(get("withdrawal")),
                       _d(bal) if bal not in (None, "") else None))
    return out


def _month(d: dt.date) -> str:
    return f"{d.year}-{d.month:02d}"


def _party(text: str) -> set:
    return {w for w in normalize_narration(text).split() if len(w) > 2 and not w.isdigit() and w not in _GENERIC}


def _eod_balances(rows: list[Row], start: Optional[dt.date], end: Optional[dt.date]) -> dict:
    """date -> balance at the end of that day, carried forward over days without transactions."""
    by_day = {}
    for r in rows:
        if r.date and r.balance is not None:
            by_day[r.date] = r.balance  # rows are in statement order, so the last one of the day wins
    if not by_day:
        return {}
    first, last = start or min(by_day), end or max(by_day)
    first, last = min(first, min(by_day)), max(last, max(by_day))
    out, cur, day = {}, None, first
    while day <= last:
        cur = by_day.get(day, cur)
        if cur is not None:
            out[day] = cur
        day += dt.timedelta(days=1)
    return out


def _recurring(debits: list[Row], months_needed: int = 2) -> list[dict]:
    """Same amount, same narration (without ids) in different months."""
    groups = defaultdict(list)
    for r in debits:
        key = (normalize_narration(r.text), r.amount)
        if key[0]:
            groups[key].append(r)
    found = []
    for (name, amount), rs in groups.items():
        months = {_month(r.date) for r in rs if r.date}
        if len(months) >= months_needed:
            found.append((name, amount, rs, sorted(months)))
    return found


def analyse_transactions(transactions, period_start: Optional[dt.date] = None, period_end: Optional[dt.date] = None,
                         opening_balance=None, large_cash: Decimal = LARGE_CASH) -> dict:
    rows = [r for r in rows_from(transactions) if r.credit or r.debit]
    dated = [r for r in rows if r.date]
    start = period_start or (min(r.date for r in dated) if dated else None)
    end = period_end or (max(r.date for r in dated) if dated else None)
    credits, debits = [r for r in rows if r.credit], [r for r in rows if r.debit]
    result: dict = {
        "period": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
        "transaction_count": len(rows),
        "totals": {"credits": money(sum((r.credit for r in rows), Decimal(0))), "debits": money(sum((r.debit for r in rows), Decimal(0))),
                   "credit_count": len(credits), "debit_count": len(debits)},
    }
    result["totals"]["net"] = money(_d(result["totals"]["credits"]) - _d(result["totals"]["debits"]))

    # ---- balances and monthly view ---------------------------------------------------------
    eod = _eod_balances(rows, start, end)
    months = sorted({_month(r.date) for r in dated})
    monthly = []
    net_by_month = []
    for m in months:
        mr = [r for r in dated if _month(r.date) == m]
        cr, dr = sum((r.credit for r in mr), Decimal(0)), sum((r.debit for r in mr), Decimal(0))
        bal = [b for d, b in eod.items() if _month(d) == m]
        monthly.append({
            "month": m, "credits": money(cr), "debits": money(dr), "net": money(cr - dr),
            "credit_count": sum(1 for r in mr if r.credit), "debit_count": sum(1 for r in mr if r.debit),
            "average_balance": money(sum(bal, Decimal(0)) / len(bal)) if bal else None,
            "min_balance": money(min(bal)) if bal else None, "max_balance": money(max(bal)) if bal else None,
        })
        net_by_month.append(float(cr - dr))
    result["monthly"] = monthly
    if eod:
        vals = list(eod.values())
        result["balances"] = {
            "average_daily_balance": money(sum(vals, Decimal(0)) / len(vals)),
            "min_balance": money(min(vals)), "max_balance": money(max(vals)),
            "min_balance_date": min(eod, key=lambda d: eod[d]).isoformat(), "days_covered": len(vals),
            "closing_balance": money(vals[-1]),
        }
    else:
        result["balances"] = None
    result["cash_flow"] = {
        "average_monthly_credits": money(sum((_d(m["credits"]) for m in monthly), Decimal(0)) / len(monthly)) if monthly else None,
        "average_monthly_debits": money(sum((_d(m["debits"]) for m in monthly), Decimal(0)) / len(monthly)) if monthly else None,
        "net_volatility": round(statistics.pstdev(net_by_month), 2) if len(net_by_month) > 1 else None,
    }

    # ---- income (salary) -------------------------------------------------------------------
    sal = [r for r in credits if _SALARY.search(r.text)]
    sal_months = sorted({_month(r.date) for r in sal if r.date})
    amounts = [r.credit for r in sal]
    result["salary"] = {
        "detected": bool(sal),
        "credits": [{"row": r.idx, "date": r.date.isoformat() if r.date else None, "amount": money(r.credit), "description": r.text} for r in sal],
        "average_amount": money(sum(amounts, Decimal(0)) / len(amounts)) if amounts else None,
        "months_with_salary": len(sal_months),
        "months_in_period": len(months),
        "regularity": round(len(sal_months) / len(months), 2) if months else None,
    }

    # ---- EMI / NACH ------------------------------------------------------------------------
    labelled = {r.idx for r in debits if _EMI.search(r.text) and not _BOUNCE.search(r.text)}
    recurring = _recurring([r for r in debits if r.idx in labelled or not _BOUNCE.search(r.text)])
    emis = []
    seen = set()
    for name, amount, rs, mths in recurring:
        if not (any(r.idx in labelled for r in rs) or len(mths) >= 3):
            continue  # a repeat of the same amount in 2 months without a loan/mandate word is too weak to call an EMI
        seen.update(r.idx for r in rs)
        emis.append({"narration": rs[0].text, "amount": money(amount), "months": mths, "count": len(rs),
                     "basis": "labelled as EMI/NACH and repeats" if any(r.idx in labelled for r in rs) else "same amount every month",
                     "rows": [r.idx for r in rs]})
    for r in debits:  # labelled once only: reported, but as a single occurrence
        if r.idx in labelled and r.idx not in seen:
            emis.append({"narration": r.text, "amount": money(r.debit), "months": [_month(r.date)] if r.date else [], "count": 1,
                         "basis": "labelled as EMI/NACH, seen once", "rows": [r.idx]})
    monthly_emi = sum((_d(e["amount"]) for e in emis if len(e["months"]) >= 2 or e["count"] > 1), Decimal(0))
    sal_avg = _d(result["salary"]["average_amount"])
    result["emi"] = {
        "obligations": emis,
        "monthly_obligation": money(monthly_emi),
        "obligation_to_salary": round(float(monthly_emi / sal_avg), 2) if sal_avg and monthly_emi else None,
    }

    # ---- bounces ---------------------------------------------------------------------------
    bounce_rows = [r for r in rows if _BOUNCE.search(r.text) and _BOUNCE_NEEDS.search(r.text)]
    result["bounces"] = {
        "count": len(bounce_rows),
        "events": [{"row": r.idx, "date": r.date.isoformat() if r.date else None, "amount": money(r.amount),
                    "direction": "credit" if r.credit else "debit", "description": r.text} for r in bounce_rows],
    }

    # ---- cash ------------------------------------------------------------------------------
    cash_in = [r for r in credits if _CASH_IN.search(r.text)]
    cash_out = [r for r in debits if _CASH_OUT.search(r.text)]
    result["cash"] = {
        "deposits_total": money(sum((r.credit for r in cash_in), Decimal(0))), "deposit_count": len(cash_in),
        "large_deposits": [{"row": r.idx, "date": r.date.isoformat() if r.date else None, "amount": money(r.credit)} for r in cash_in if r.credit >= large_cash],
        "large_deposit_threshold": money(large_cash),
        "withdrawals_total": money(sum((r.debit for r in cash_out), Decimal(0))), "withdrawal_count": len(cash_out),
    }

    # ---- circular transactions -------------------------------------------------------------
    circular = []
    used = set()
    for out in debits:
        if out.debit < CIRCULAR_MIN or not out.date or out.idx in {b.idx for b in bounce_rows}:
            continue
        pa = _party(out.text)
        for back in credits:
            if back.idx in used or back.credit != out.debit or not back.date:
                continue
            if 0 <= (back.date - out.date).days <= CIRCULAR_DAYS and pa & _party(back.text):
                circular.append({"out_row": out.idx, "in_row": back.idx, "amount": money(out.debit), "party": sorted(pa & _party(back.text)),
                                 "days_apart": (back.date - out.date).days})
                used.add(back.idx)
                break
    result["circular"] = {"count": len(circular), "pairs": circular,
                          "note": "Same amount out and back from the same party within %d days. A hint to check, not proof." % CIRCULAR_DAYS}

    # ---- biggest movements -----------------------------------------------------------------
    def top(rs):
        return [{"row": r.idx, "date": r.date.isoformat() if r.date else None, "amount": money(r.amount), "description": r.text}
                for r in sorted(rs, key=lambda x: x.amount, reverse=True)[:5]]
    result["largest"] = {"credits": top(credits), "debits": top(debits)}

    # ---- anomalies for a simple, explainable dashboard ------------------------------------
    anomalies = []
    if len(monthly) >= 2:
        prior = None
        for m in monthly:
            debits_m = _d(m["debits"])
            if prior and prior > 0:
                change = (debits_m - prior) / prior
                if change >= Decimal("0.5"):
                    anomalies.append({
                        "code": "spending_spike",
                        "severity": "medium",
                        "month": m["month"],
                        "message": f"Spending in {m['month']} was {round(float(change) * 100)}% higher than the previous month.",
                    })
            prior = debits_m
    for item in result["largest"]["debits"][:3]:
        anomalies.append({
            "code": "large_debit",
            "severity": "medium",
            "row": item["row"],
            "month": item["date"][:7] if item["date"] else None,
            "message": f"Large debit of {item['amount']} for {item['description'] or 'no description'}.",
        })
    if result["bounces"]["count"]:
        anomalies.append({
            "code": "bounced_items",
            "severity": "high",
            "count": result["bounces"]["count"],
            "message": f"{result['bounces']['count']} bounced or returned item(s) need review.",
        })
    result["anomalies"] = anomalies
    recurring = _recurring(debits, 2)
    result["recurring"] = [
        {
            "merchant": name,
            "amount": money(amount),
            "count": len(rs),
            "months": sorted(months),
            "rows": [r.idx for r in rs],
        }
        for name, amount, rs, months in recurring[:20]
    ]
    return result
