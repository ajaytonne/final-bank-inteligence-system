"""Merchant identification: turn an unclear bank narration into a readable merchant name.

Rules only (tokens, aliases, a confidence score). No AI is involved in any decision.
The original narration is never changed: everything below works on a normalized copy.
Saved corrections live in their own table (`merchant_mappings`) and never touch statements.
"""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

UNKNOWN = "Unknown Merchant"
CATEGORIES = ("Shopping", "Food", "Groceries", "Transport", "Utilities", "Entertainment", "Banking", "Other")
RELIABLE_THRESHOLD = 0.70  # below this the answer is "Unknown Merchant"

# ---- 1. Merchant dictionary ------------------------------------------------------------------
# name -> (category, aliases). An alias matches only as whole words, in order ("big basket").
BRANDS = {
    "Amazon": ("Shopping", ["amazon", "amzn", "amazonpay"]),
    "Flipkart": ("Shopping", ["flipkart", "fkrt"]),
    "Myntra": ("Shopping", ["myntra"]),
    "Ajio": ("Shopping", ["ajio"]),
    "Meesho": ("Shopping", ["meesho"]),
    "Nykaa": ("Shopping", ["nykaa"]),
    "Croma": ("Shopping", ["croma"]),
    "Decathlon": ("Shopping", ["decathlon"]),
    "Lenskart": ("Shopping", ["lenskart"]),
    "Swiggy": ("Food", ["swiggy"]),
    "Zomato": ("Food", ["zomato"]),
    "Domino's": ("Food", ["dominos", "domino"]),
    "McDonald's": ("Food", ["mcdonalds", "mcdonald"]),
    "KFC": ("Food", ["kfc"]),
    "Starbucks": ("Food", ["starbucks"]),
    "Pizza Hut": ("Food", ["pizza hut", "pizzahut"]),
    "Burger King": ("Food", ["burger king", "burgerking"]),
    "Cafe Coffee Day": ("Food", ["cafe coffee day", "ccd"]),
    "Haldiram's": ("Food", ["haldirams", "haldiram"]),
    "DMart": ("Groceries", ["dmart", "d mart", "avenue supermarts"]),
    "BigBasket": ("Groceries", ["bigbasket", "big basket"]),
    "Blinkit": ("Groceries", ["blinkit", "grofers"]),
    "Zepto": ("Groceries", ["zepto", "zeptonow"]),
    "Swiggy Instamart": ("Groceries", ["swiggy instamart", "instamart"]),
    "JioMart": ("Groceries", ["jiomart"]),
    "Reliance Fresh": ("Groceries", ["reliance fresh", "reliance smart"]),
    "Spencer's": ("Groceries", ["spencers"]),
    "Country Delight": ("Groceries", ["country delight", "countrydelight"]),
    "Uber": ("Transport", ["uber"]),
    "Ola": ("Transport", ["ola", "olacabs", "ola cabs"]),
    "Rapido": ("Transport", ["rapido"]),
    "IRCTC": ("Transport", ["irctc"]),
    "RedBus": ("Transport", ["redbus"]),
    "Delhi Metro": ("Transport", ["dmrc", "delhi metro"]),
    "FASTag": ("Transport", ["fastag"]),
    "Indian Oil": ("Transport", ["indian oil", "indianoil", "iocl"]),
    "HPCL": ("Transport", ["hpcl", "hp petrol"]),
    "BPCL": ("Transport", ["bpcl", "bharat petroleum"]),
    "MakeMyTrip": ("Transport", ["makemytrip", "mmt"]),
    "BluSmart": ("Transport", ["blusmart"]),
    "Airtel": ("Utilities", ["airtel", "bharti airtel"]),
    "Jio": ("Utilities", ["jio", "reliance jio"]),
    "Vodafone Idea": ("Utilities", ["vodafone", "vodafone idea"]),
    "BSNL": ("Utilities", ["bsnl"]),
    "Tata Power": ("Utilities", ["tata power", "tatapower"]),
    "Adani Electricity": ("Utilities", ["adani electricity"]),
    "MSEDCL": ("Utilities", ["msedcl", "mahavitaran"]),
    "BESCOM": ("Utilities", ["bescom"]),
    "Tata Play": ("Utilities", ["tata play", "tataplay", "tata sky", "tatasky"]),
    "Mahanagar Gas": ("Utilities", ["mahanagar gas"]),
    "ACT Fibernet": ("Utilities", ["act fibernet", "actfibernet"]),
    "Hathway": ("Utilities", ["hathway"]),
    "Netflix": ("Entertainment", ["netflix"]),
    "Spotify": ("Entertainment", ["spotify"]),
    "Disney+ Hotstar": ("Entertainment", ["hotstar", "disney hotstar", "jiohotstar"]),
    "Amazon Prime": ("Entertainment", ["amazon prime", "primevideo", "prime video"]),
    "BookMyShow": ("Entertainment", ["bookmyshow"]),
    "SonyLIV": ("Entertainment", ["sonyliv", "sony liv"]),
    "YouTube": ("Entertainment", ["youtube"]),
    "Zee5": ("Entertainment", ["zee5"]),
    "PVR INOX": ("Entertainment", ["pvr", "inox", "pvr inox"]),
}

# Generic services: readable labels, not brands. Lower confidence, and a brand match always wins.
SERVICES = {
    "ATM Withdrawal": ("Banking", ["atm cash withdrawal", "atm withdrawal", "atm wdl", "cash withdrawal"]),
    "Bank Interest": ("Banking", ["interest credit", "interest paid", "credit interest"]),
    "Bank Charges": ("Banking", ["service charge", "sms charges", "bank charges"]),
    "Loan EMI": ("Banking", ["emi", "loan emi"]),
    "Mobile Recharge": ("Utilities", ["mobile recharge", "recharge"]),
    "Electricity Bill": ("Utilities", ["electricity bill", "electricity"]),
    "Petrol Pump": ("Transport", ["petrol pump", "petrol", "diesel"]),
}

# ---- 2. Normalization ------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]+")
# Payment-format words, IDs and UPI handle suffixes: noise for the displayed merchant name.
_PAYMENT_MODES = {
    "upi": "UPI", "pos": "POS", "ecom": "Card", "pur": "Card", "card": "Card", "imps": "IMPS",
    "neft": "NEFT", "rtgs": "RTGS", "atm": "ATM", "ach": "Auto-debit", "nach": "Auto-debit",
    "ecs": "Auto-debit", "chq": "Cheque", "cheque": "Cheque",
}
_PAYMENT_APPS = {
    "ybl": "PhonePe", "ibl": "PhonePe", "axl": "PhonePe", "phonepe": "PhonePe",
    "paytm": "Paytm", "ptys": "Paytm", "ptyes": "Paytm", "pthdfc": "Paytm", "ptsbi": "Paytm",
    "okaxis": "Google Pay", "okhdfcbank": "Google Pay", "oksbi": "Google Pay", "okicici": "Google Pay",
    "gpay": "Google Pay", "googlepay": "Google Pay", "apl": "Amazon Pay", "bhim": "BHIM",
}
_NOISE = {"p2m", "p2p", "txn", "ref", "vpa", "utr", "rrn", "mob", "dr", "cr", "by", "to", "from", "via", "trf", "ft", "tpt"}
_DROP = set(_PAYMENT_MODES) - {"atm"} | set(_PAYMENT_APPS) | _NOISE


def _tokens(narration: Optional[str]) -> list[str]:
    return _WORD.findall(str(narration or "").lower())


def _is_code(token: str) -> bool:
    """Pure numbers (ids, dates) and long letter+digit codes (TXN62992312, STORE01). Brands like zee5 stay."""
    return token.isdigit() or (len(token) >= 5 and any(c.isdigit() for c in token))


def _core(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in _DROP and not _is_code(t)]


def normalize_narration(narration: Optional[str]) -> str:
    """Lower-case words of the narration without ids, dates, payment codes and handles (a copy, for matching)."""
    return " ".join(_core(_tokens(narration)))


def detect_platform(narration: Optional[str]) -> Optional[str]:
    """The payment format / app seen in the narration, e.g. "UPI via PhonePe", or None."""
    mode = app = None
    for t in _tokens(narration):
        mode = mode or _PAYMENT_MODES.get(t)
        app = app or _PAYMENT_APPS.get(t)
    if mode and app:
        return f"{mode} via {app}"
    return mode or app


# ---- 3. Alias matching -----------------------------------------------------------------------
def _alias_index():
    rows = []
    for kind, table in (("brand", BRANDS), ("service", SERVICES)):
        for name, (category, aliases) in table.items():
            for alias in aliases:
                rows.append((tuple(alias.split()), name, category, kind))
    return rows


_SYSTEM_ALIASES = _alias_index()


def match_merchant_alias(core: list[str], aliases) -> list[dict]:
    """Every place an alias appears as whole words, in order. Matches inside a longer match are dropped.

    `aliases` is an iterable of (alias_tokens, name, category, kind).
    """
    found = []
    for alias_tokens, name, category, kind in aliases:
        n = len(alias_tokens)
        for start in range(len(core) - n + 1):
            if tuple(core[start:start + n]) == alias_tokens:
                found.append({"start": start, "end": start + n, "alias": " ".join(alias_tokens), "name": name,
                              "category": category, "kind": kind})
    return [m for m in found if not any(o is not m and o["start"] <= m["start"] and m["end"] <= o["end"]
                                        and (o["end"] - o["start"]) > (m["end"] - m["start"]) for o in found)]


def map_merchant_category(merchant_name: str) -> str:
    """Category of a known merchant name, "Other" when we do not know it."""
    for table in (BRANDS, SERVICES):
        for name, (category, _) in table.items():
            if name.lower() == str(merchant_name).strip().lower():
                return category
    return "Other"


def calculate_confidence(kind: str, alias: str, covers_all: bool, platform: Optional[str]) -> float:
    """0..1. Brands start higher than generic services; a known payment format and a full-text match add a little."""
    score = 0.90 if kind == "brand" else 0.75
    if platform:
        score += 0.05
    if covers_all:
        score += 0.03
    if len(alias) <= 3 and not platform:
        score -= 0.10  # very short aliases ("ola", "kfc") are easy to hit by accident
    return round(max(0.0, min(1.0, score)), 2)


# ---- 4. Identification -----------------------------------------------------------------------
def _result(name, category, status, confidence, reason, platform, source, alias=None):
    return {"merchant_name": name, "category": category, "status": status, "confidence": confidence,
            "reason": reason, "platform": platform, "source": source, "matched_alias": alias}


def _unknown(reason, platform, confidence=0.0):
    return _result(UNKNOWN, "Other", "Unknown", confidence, reason, platform, "none")


def _prepare_user(mappings) -> list:
    rows = []
    for m in mappings or []:
        for alias in m.get("aliases", []):
            tokens = tuple(_core(_tokens(alias)))
            if tokens:
                rows.append((tokens, m["merchant_name"], m["category"], "user"))
    return rows


def identify_merchant(narration: Optional[str], user_mappings=None, threshold: float = RELIABLE_THRESHOLD) -> dict:
    """Steps: saved corrections first, then known aliases, then confidence check. Never raises, never guesses."""
    return _identify(narration, _prepare_user(user_mappings), threshold)


def _identify(narration, user_rows, threshold) -> dict:
    platform = detect_platform(narration)
    core = _core(_tokens(narration))
    if not core:
        return _unknown("Nothing left to identify after removing ids, dates and payment codes.", platform)

    # 1. Saved user corrections (always trusted; the longest alias wins, then the newest because rows are newest first)
    hits = match_merchant_alias(core, user_rows)
    if hits:
        best = max(hits, key=lambda m: m["end"] - m["start"])
        return _result(best["name"], best["category"], "User Corrected", 1.0,
                       f"Matches your saved correction for '{best['alias']}'.", platform, "user", best["alias"])

    # 2. Built-in aliases. A brand always beats a generic service label.
    hits = match_merchant_alias(core, _SYSTEM_ALIASES)
    if any(h["kind"] == "brand" for h in hits):
        hits = [h for h in hits if h["kind"] == "brand"]
    names = sorted({h["name"] for h in hits})
    if not hits:
        return _unknown("No known merchant or service name found in the narration.", platform)
    if len(names) > 1:
        return _unknown(f"Ambiguous: the narration mentions {' and '.join(names)}.", platform, 0.3)

    best = max(hits, key=lambda m: m["end"] - m["start"])
    covers_all = (best["end"] - best["start"]) == len(core)
    confidence = calculate_confidence(best["kind"], best["alias"], covers_all, platform)
    if confidence < threshold:
        return _unknown(f"'{best['alias']}' is only a weak match (confidence {confidence:.2f}).", platform, confidence)
    what = "merchant name" if best["kind"] == "brand" else "service keyword"
    where = f" (payment format: {platform})" if platform else ""
    return _result(best["name"], best["category"], "Identified", confidence,
                   f"Found the {what} '{best['alias']}'{where}.", platform, "system", best["alias"])


def identify_merchants(narrations, user_mappings=None, threshold: float = RELIABLE_THRESHOLD) -> list[dict]:
    rows = _prepare_user(user_mappings)  # prepared once for the whole batch
    return [_identify(n, rows, threshold) for n in narrations]


# ---- 5. Saved corrections (own table, own rows; statements are never touched) ----------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS merchant_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_name TEXT NOT NULL,
    aliases TEXT NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('system', 'user', 'imported')),
    confidence_threshold REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["aliases"] = json.loads(d["aliases"])
    return d


class MerchantMappingStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def list(self, q: Optional[str] = None) -> list[dict]:
        """Newest first, so the newest correction wins when two have an alias of the same length."""
        with self._conn() as c:
            rows = [_row(r) for r in c.execute("SELECT * FROM merchant_mappings ORDER BY updated_at DESC, id DESC")]
        if q and q.strip():
            needle = q.strip().lower()
            rows = [r for r in rows if needle in r["merchant_name"].lower() or any(needle in a for a in r["aliases"])]
        return rows

    def get_or_create_merchant_mapping(self, merchant_name: str, category: str, source: str = "user") -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as c:
            r = c.execute("SELECT * FROM merchant_mappings WHERE lower(merchant_name) = lower(?) AND source = ?",
                          (merchant_name, source)).fetchone()
            if r is None:
                cur = c.execute(
                    "INSERT INTO merchant_mappings (merchant_name, aliases, category, source, confidence_threshold,"
                    " created_at, updated_at) VALUES (?, '[]', ?, ?, NULL, ?, ?)",
                    (merchant_name, category, source, now, now),
                )
                return _row(c.execute("SELECT * FROM merchant_mappings WHERE id = ?", (cur.lastrowid,)).fetchone())
            if r["category"] != category:
                c.execute("UPDATE merchant_mappings SET category = ?, updated_at = ? WHERE id = ?", (category, now, r["id"]))
                r = c.execute("SELECT * FROM merchant_mappings WHERE id = ?", (r["id"],)).fetchone()
            return _row(r)

    def save_manual_mapping(self, narration: str, merchant_name: str, category: str, alias: Optional[str] = None) -> dict:
        """Remember "narrations like this one are <merchant_name>". Raises ValueError for unusable input."""
        merchant_name = " ".join(str(merchant_name).split())
        if not merchant_name or merchant_name.lower() == UNKNOWN.lower():
            raise ValueError("Enter a merchant name.")
        if category not in CATEGORIES:
            raise ValueError(f"Category must be one of: {', '.join(CATEGORIES)}.")
        alias_text = " ".join(_core(_tokens(alias if alias else narration)))
        if not alias_text:
            raise ValueError("The narration has no merchant text to remember (only ids or payment codes).")
        mapping = self.get_or_create_merchant_mapping(merchant_name, category, "user")
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as c:
            # An alias belongs to one merchant only: move it away from any other correction that has it.
            for r in c.execute("SELECT id, aliases FROM merchant_mappings WHERE source = 'user' AND id != ?", (mapping["id"],)).fetchall():
                aliases = json.loads(r["aliases"])
                if alias_text in aliases:
                    aliases.remove(alias_text)
                    c.execute("UPDATE merchant_mappings SET aliases = ?, updated_at = ? WHERE id = ?", (json.dumps(aliases), now, r["id"]))
            aliases = mapping["aliases"]
            if alias_text not in aliases:
                aliases.append(alias_text)
            c.execute("UPDATE merchant_mappings SET aliases = ?, updated_at = ? WHERE id = ?", (json.dumps(aliases), now, mapping["id"]))
            return _row(c.execute("SELECT * FROM merchant_mappings WHERE id = ?", (mapping["id"],)).fetchone())

    def delete(self, mapping_id: int) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM merchant_mappings WHERE id = ?", (mapping_id,)).rowcount > 0
