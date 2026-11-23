"""Reconciliation engine: compares the transactions of two statements.

Pure functions: no database, no AI, no changes to any transaction. It only returns result rows (derived data)
that the caller stores separately. Every row carries a plain-language reason and a confidence score.

Matching priorities (a candidate always needs the same amount, a compatible direction and a date inside the window):
  1. Same reference                       -> Matched (or Timing Difference if the dates differ)
  2. Description compatible               -> Matched (or Timing Difference)
  3. Partly similar description / hints   -> Possible Match (a person decides)
  4. Nothing but amount, direction, date  -> Possible Match with low confidence (a person decides)
Equal amounts alone never give a Matched result. When several candidates have identical evidence the pairs
are marked Manual Review. A transaction is used by at most one pair.
"""
import datetime as dt
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional

from statement_analyser.services.merchant_identifier import normalize_narration  # reuse the noise-free copy of a narration

INTERNAL, INTER_BANK = "internal", "inter_bank"
MATCHED, POSSIBLE, UNMATCHED, DUPLICATE = "Matched", "Possible Match", "Unmatched", "Duplicate Candidate"
MISSING, TIMING, MANUAL, REJECTED = "Missing Transaction", "Timing Difference", "Manual Review", "Rejected Match"
PAIR_STATUSES = (MATCHED, TIMING)  # a matched pair: counts as matched, amounts are summed once
SIM_STRONG, SIM_WEAK = 0.6, 0.3
_TRANSFER_WORDS = {"neft", "imps", "rtgs", "upi", "transfer", "trf"}
_GENERIC_BANK_WORDS = {"bank", "ltd", "limited", "india", "the", "and", "pvt", "private"}


@dataclass
class Txn:
    idx: int  # position in the saved statement's transaction list
    date: Optional[dt.date]
    description: str
    reference: str
    amount: Decimal
    direction: str  # "debit" (withdrawal) or "credit" (deposit)


@dataclass
class Side:
    statement_id: int
    label: str
    bank_name: str
    last4: str
    period_start: Optional[dt.date]
    period_end: Optional[dt.date]
    txns: list = field(default_factory=list)
    account_id: Optional[int] = None
    owned: bool = False  # the user confirmed this account is theirs
    skipped: int = 0  # rows without an amount (left untouched in the statement)
    currency: str = "INR"


# ---- building the input ---------------------------------------------------------------------
def build_side(statement_id: int, statement, account: Optional[dict] = None) -> Side:
    """`statement` is a ReviewedStatement; `account` an optional saved bank account row."""
    txns, skipped = [], 0
    for i, t in enumerate(statement.transactions):
        credit, debit = t.deposit or Decimal(0), t.withdrawal or Decimal(0)
        if credit > 0:
            txns.append(Txn(i, t.date, t.description or "", t.reference or "", credit, "credit"))
        elif debit > 0:
            txns.append(Txn(i, t.date, t.description or "", t.reference or "", debit, "debit"))
        else:
            skipped += 1
    h = statement.header
    dates = [t.date for t in txns if t.date]
    account = account or {}
    masked = account.get("account_number_masked") or h.account_number_masked or ""
    return Side(
        statement_id=statement_id,
        label=account.get("account_label") or statement.file_name,
        bank_name=account.get("bank_name") or h.bank_name or "",
        last4="".join(c for c in masked if c.isdigit())[-4:],
        period_start=h.period_start or (min(dates) if dates else None),
        period_end=h.period_end or (max(dates) if dates else None),
        txns=txns,
        account_id=account.get("id"),
        owned=bool(account.get("ownership_confirmed")),
        skipped=skipped,
        currency=h.currency or "INR",
    )


def check_accounts(kind: str, a: Side, b: Side) -> Optional[str]:
    """An error message when the chosen statements do not fit the reconciliation type, else None."""
    if a.currency != b.currency:
        return "Cannot compare statements with different currencies. Convert both to the same currency first."
    if a.account_id and b.account_id:
        same = a.account_id == b.account_id
    elif a.bank_name and b.bank_name and a.last4 and b.last4:
        same = (a.bank_name.lower(), a.last4) == (b.bank_name.lower(), b.last4)
    else:
        return None  # not enough information to judge; allowed
    if kind == INTERNAL and not same:
        return "Internal reconciliation needs two statements from the same bank account."
    if kind == INTER_BANK and same:
        return "These two statements belong to the same account. Use Internal reconciliation instead."
    return None


# ---- small helpers --------------------------------------------------------------------------
def _norm_ref(ref: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(ref or "").upper())


def similarity(a: str, b: str) -> float:
    """0..1 between two narrations (ids and payment codes removed first): the better of word overlap and text ratio."""
    na, nb = normalize_narration(a), normalize_narration(b)
    if not na or not nb:
        return 0.0
    sa, sb = set(na.split()), set(nb.split())
    return round(max(len(sa & sb) / len(sa | sb), SequenceMatcher(None, na, nb).ratio()), 2)


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))


def _transfer_like(text: str) -> bool:
    return bool(_words(text) & _TRANSFER_WORDS)


def _mentions(text: str, side: Side) -> bool:
    """The narration names the other account's bank or shows its last four digits."""
    bank_words = {w for w in re.findall(r"[a-z]+", side.bank_name.lower()) if len(w) >= 3 and w not in _GENERIC_BANK_WORDS}
    if bank_words & _words(text):
        return True
    return bool(side.last4) and re.search(rf"(?<!\d){side.last4}(?!\d)", str(text)) is not None


def _snap(t: Optional[Txn]):
    if t is None:
        return None
    return {"date": t.date.isoformat() if t.date else None, "description": t.description, "reference": t.reference,
            "amount": str(t.amount), "direction": t.direction}


def _row(a_side, a, b_side, b, match_type, status, reason, confidence, confirmation, internal=0):
    return {
        "a_statement_id": a_side.statement_id if a is not None else None, "a_index": a.idx if a is not None else None,
        "b_statement_id": b_side.statement_id if b is not None else None, "b_index": b.idx if b is not None else None,
        "match_type": match_type, "status": status, "reason": reason, "confidence": round(confidence, 2),
        "confirmation_status": confirmation, "internal_transfer": int(internal),
        "a_reference": a.reference if a is not None else "", "b_reference": b.reference if b is not None else "",
        "a_snapshot": _snap(a), "b_snapshot": _snap(b),
    }


def _money(v: Decimal) -> str:
    return f"₹{v:,.2f}"


# ---- evaluating one candidate pair ----------------------------------------------------------
def _evaluate(a: Txn, b: Txn, kind: str, window: int, sa: Side, sb: Side) -> Optional[dict]:
    """The evidence for a pair that has the same amount, or None when direction or dates rule it out."""
    if (kind == INTERNAL) != (a.direction == b.direction):
        return None  # same account: both debits or both credits. Inter-bank: a debit against a credit.
    diff = abs((a.date - b.date).days) if a.date and b.date else None
    if diff is not None and diff > window:
        return None
    ref_equal = bool(_norm_ref(a.reference)) and _norm_ref(a.reference) == _norm_ref(b.reference)
    sim = similarity(a.description, b.description)
    transfer_hint = kind == INTER_BANK and _transfer_like(a.description) and _transfer_like(b.description)
    account_hint = kind == INTER_BANK and (_mentions(a.description, sb) or _mentions(b.description, sa))
    d = diff or 0

    evidence = [f"same amount {_money(a.amount)}", "directions fit" if kind == INTER_BANK else "same direction"]
    evidence.append("same date" if diff == 0 else f"dates differ by {diff} day(s)" if diff is not None else "a date is missing")
    if ref_equal:
        level, conf = 1, 0.95 - 0.02 * d + (0.03 if sim >= 0.5 else 0)
        evidence.insert(0, f"same reference {a.reference}")
    elif sim >= SIM_STRONG or (account_hint and transfer_hint):
        level, conf = 2, 0.80 + 0.10 * sim - 0.03 * d
        evidence.append(f"descriptions are compatible (similarity {sim:.2f})" if sim >= SIM_STRONG else "narrations name the other account and a transfer")
    elif sim >= SIM_WEAK or transfer_hint or account_hint:
        level, conf = 3, 0.55 + 0.15 * sim - 0.03 * d
        evidence.append(f"descriptions only partly alike (similarity {sim:.2f})" if sim >= SIM_WEAK else "a transfer or the other account is mentioned")
    else:
        level, conf = 4, 0.35 - 0.02 * d
        evidence.append("no reference or description evidence: amount alone is not enough")
    if diff is None:
        level = max(level, 3)  # the date cannot be checked, so a person has to decide
    conf = max(0.05, min(0.99, conf))
    if level <= 2:
        status, confirmation = (TIMING if d > 0 else MATCHED), "auto"
    else:
        status, confirmation = POSSIBLE, "pending"
    return {"a": a, "b": b, "level": level, "conf": round(conf, 2), "status": status, "confirmation": confirmation,
            "match_type": ("Reference", "Amount + description", "Description + date", "Amount only")[level - 1],
            "reason": (lambda text: text[0].upper() + text[1:] + ".")("; ".join(evidence))}


# ---- the engine -----------------------------------------------------------------------------
def reconcile(a: Side, b: Side, kind: str, window: int) -> dict:
    """Compare A with B. Returns {"rows", "notes", "total_a", "total_b"}. Inputs are not modified."""
    notes, rows = [], []
    inter = kind == INTER_BANK
    both_owned = inter and a.owned and b.owned

    # Which transactions can be compared at all? Internal: only the overlapping period. Inter-bank: the other
    # statement's period plus the date window. Others are labelled "period gap", not errors.
    starts = [s for s in (a.period_start, b.period_start) if s]
    ends = [e for e in (a.period_end, b.period_end) if e]
    lo, hi = (max(starts) if starts else None), (min(ends) if ends else None)

    def eligible(t: Txn, other: Side) -> bool:
        if t.date is None:
            return True
        if inter:
            pad = dt.timedelta(days=window)
            return (other.period_start is None or t.date >= other.period_start - pad) and (other.period_end is None or t.date <= other.period_end + pad)
        return (lo is None or t.date >= lo) and (hi is None or t.date <= hi)

    def span(s: Side) -> str:
        return f"{s.period_start or '?'} to {s.period_end or '?'}"

    if inter:
        notes.append(f"Statement A covers {span(a)}; statement B covers {span(b)}. A date window of {window} day(s) is allowed for transfers that settle on different days.")
    elif lo and hi and lo > hi:
        notes.append(f"The statements cover different periods ({span(a)} and {span(b)}) and do not overlap, so nothing could be compared. Their transactions are labelled as period gaps, not errors.")
    else:
        notes.append(f"Overlapping period: {lo or '?'} to {hi or '?'}. Only transactions inside it are compared; anything outside is a period gap, not an error.")
        if (a.period_start, a.period_end) != (b.period_start, b.period_end):
            notes.append(f"Statement A covers {span(a)}; statement B covers {span(b)}.")
    for s, name in ((a, "A"), (b, "B")):
        if s.skipped:
            notes.append(f"Statement {name}: {s.skipped} row(s) without an amount were skipped (they are unchanged in the statement).")

    ea = [t for t in a.txns if eligible(t, b)]
    eb = [t for t in b.txns if eligible(t, a)]

    # 1. Candidate pairs. Only transactions with the same amount are compared (also keeps it fast).
    by_amount = defaultdict(list)
    for t in eb:
        by_amount[t.amount].append(t)
    cands = []
    for ta in ea:
        for tb in by_amount.get(ta.amount, []):
            c = _evaluate(ta, tb, kind, window, a, b)
            if c:
                cands.append(c)
    cands.sort(key=lambda c: (c["level"], -c["conf"], c["a"].idx, c["b"].idx))
    by_a, by_b = defaultdict(list), defaultdict(list)
    for c in cands:
        by_a[c["a"].idx].append(c)
        by_b[c["b"].idx].append(c)

    # 2. Best evidence first. A transaction joins one pair only; identical evidence means a person must choose.
    used_a, used_b = set(), set()
    for c in cands:
        ia, ib = c["a"].idx, c["b"].idx
        if ia in used_a or ib in used_b:
            continue
        key = (c["level"], c["conf"])
        tied = [x for x in by_a[ia] + by_b[ib] if (x["level"], x["conf"]) == key and x["a"].idx not in used_a and x["b"].idx not in used_b]
        tied = list({id(x): x for x in tied}.values())
        if len(tied) > 1:
            for x in tied:
                rows.append(_row(a, x["a"], b, x["b"], x["match_type"], MANUAL,
                                 f"{len(tied)} possible pairs have identical evidence, so none was chosen automatically. {x['reason']}",
                                 x["conf"], "pending", both_owned and x["level"] <= 3))
                used_a.add(x["a"].idx)
                used_b.add(x["b"].idx)
            continue
        used_a.add(ia)
        used_b.add(ib)
        reason, internal = c["reason"], both_owned and c["level"] <= 3  # amount alone is never a transfer hint
        if internal:
            reason += " Both accounts are marked as yours: possible internal transfer (confirm it to leave it out of consolidated totals)."
        rows.append(_row(a, c["a"], b, c["b"], c["match_type"], c["status"], reason, c["conf"], c["confirmation"], internal))

    # 3. Same reference but another check failed (amount, direction or dates): a person has to look.
    by_ref = defaultdict(list)
    for tb in eb:
        if tb.idx not in used_b and _norm_ref(tb.reference):
            by_ref[_norm_ref(tb.reference)].append(tb)
    for ta in ea:
        if ta.idx in used_a or not _norm_ref(ta.reference):
            continue
        for tb in by_ref.get(_norm_ref(ta.reference), []):
            if tb.idx in used_b:
                continue
            failed = []
            if ta.amount != tb.amount:
                failed.append(f"amounts differ ({_money(ta.amount)} vs {_money(tb.amount)})")
            if (kind == INTERNAL) != (ta.direction == tb.direction):
                failed.append("directions do not fit")
            if ta.date and tb.date and abs((ta.date - tb.date).days) > window:
                failed.append(f"dates are {abs((ta.date - tb.date).days)} days apart (window {window})")
            rows.append(_row(a, ta, b, tb, "Reference", MANUAL, f"Same reference {ta.reference}, but {' and '.join(failed) or 'a check failed'}.",
                             0.5, "pending", both_owned))
            used_a.add(ta.idx)
            used_b.add(tb.idx)
            break

    # 4. Possible duplicates inside one statement. They are only shown; nothing is deleted.
    for side in (a, b):
        groups = defaultdict(list)
        for t in side.txns:
            groups[(t.date, t.amount, t.direction, normalize_narration(t.description))].append(t)
        for g in groups.values():
            for other in g[1:]:
                refs = (_norm_ref(g[0].reference), _norm_ref(other.reference))
                if all(refs) and refs[0] != refs[1]:
                    continue  # different references: two separate transactions
                same_ref = all(refs)
                rows.append(_row(side, g[0], side, other, "Duplicate", DUPLICATE,
                                 f"Same date, amount ({_money(g[0].amount)}), direction and description appear more than once in {side.label}"
                                 f"{' with the same reference' if same_ref else ' (a reference is missing)'}. Shown for review; nothing is deleted.",
                                 0.90 if same_ref else 0.70, "pending"))

    # 5. Everything still without a partner.
    for side, other, name, own, used, is_a in ((a, b, "A", ea, used_a, True), (b, a, "B", eb, used_b, False)):
        ok = {t.idx for t in own}
        for t in side.txns:
            if t.idx in used:
                continue
            args = (side, t, other, None) if is_a else (other, None, side, t)
            if t.idx not in ok:
                why = f"Period gap: {t.date} is outside what statement {'B' if is_a else 'A'} covers ({span(other)}), so it cannot be matched. This is not an error."
                rows.append(_row(*args, "Period gap", UNMATCHED, why, 1.0, "none"))
            elif inter:
                way = "outgoing (debit)" if t.direction == "debit" else "incoming (credit)"
                counterpart = "credit" if t.direction == "debit" else "debit"
                why = f"Unmatched {way} {_money(t.amount)}: no {counterpart} of that amount in the other statement within {window} day(s)."
                if _transfer_like(t.description):
                    why += " It looks like a transfer but appears in only this statement."
                rows.append(_row(*args, "Unmatched", UNMATCHED, why, 1.0, "none"))
            else:
                why = f"Inside the overlapping period but not found in statement {'B' if is_a else 'A'}."
                rows.append(_row(*args, "Missing", MISSING, why, 1.0, "none"))

    matched_pairs = [r for r in rows if r["status"] in PAIR_STATUSES]
    if not inter and a.txns and len(matched_pairs) == len(a.txns) == len(b.txns):
        notes.append("Every transaction matched: statement B may be a second upload of statement A.")
    return {"rows": rows, "notes": notes, "total_a": len(a.txns), "total_b": len(b.txns)}


# ---- summary and consolidated totals --------------------------------------------------------
def _amount(row: dict) -> Decimal:
    snap = row.get("a_snapshot") or row.get("b_snapshot")
    return Decimal(snap["amount"]) if snap else Decimal(0)


def is_confirmed_transfer(row: dict) -> bool:
    return bool(row["internal_transfer"]) and row["confirmation_status"] == "confirmed" and row["status"] in PAIR_STATUSES


def build_summary(rows: list, total_a: int, total_b: int) -> dict:
    """Counts and amounts from the stored result rows (so it follows confirmations and rejections)."""
    counts = Counter(r["status"] for r in rows)
    gaps = [r for r in rows if r["match_type"] == "Period gap"]  # outside the other statement's dates: not errors
    matched = [r for r in rows if r["status"] in PAIR_STATUSES]
    unmatched = [r for r in rows if r["status"] in (UNMATCHED, MISSING) and r["match_type"] != "Period gap"]
    return {
        "total_a": total_a, "total_b": total_b,
        "matched": counts[MATCHED], "timing_differences": counts[TIMING], "possible_matches": counts[POSSIBLE],
        "manual_review": counts[MANUAL], "unmatched": len(unmatched), "period_gaps": len(gaps),
        "missing_transactions": counts[MISSING], "duplicate_candidates": counts[DUPLICATE], "rejected": counts[REJECTED],
        "confirmed_internal_transfers": sum(1 for r in rows if is_confirmed_transfer(r)),
        "total_matched_amount": str(sum((_amount(r) for r in matched), Decimal(0))),
        "total_unmatched_amount": str(sum((_amount(r) for r in unmatched), Decimal(0))),
    }


def consolidate(sides: list, rows: list) -> dict:
    """Income and expenses of the given sides. Only CONFIRMED internal transfers are left out."""
    excluded = set()
    for r in rows:
        if is_confirmed_transfer(r):
            excluded.add((r["a_statement_id"], r["a_index"]))
            excluded.add((r["b_statement_id"], r["b_index"]))
    raw_in = raw_out = skip_in = skip_out = Decimal(0)
    for s in sides:
        for t in s.txns:
            skipped = (s.statement_id, t.idx) in excluded
            if t.direction == "credit":
                raw_in += t.amount
                skip_in += t.amount if skipped else 0
            else:
                raw_out += t.amount
                skip_out += t.amount if skipped else 0
    return {"income": str(raw_in - skip_in), "expenses": str(raw_out - skip_out), "savings": str(raw_in - skip_in - raw_out + skip_out),
            "income_before_exclusion": str(raw_in), "expenses_before_exclusion": str(raw_out),
            "excluded_transfer_count": len(excluded) // 2, "excluded_amount": str(skip_out)}
