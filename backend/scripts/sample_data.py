"""Dummy statement generator (synthetic data only)."""
import io
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pymupdf
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


@dataclass
class Txn:
    day: date
    desc: str
    ref: str
    withdrawal: Decimal | None
    deposit: Decimal | None


def inr(v: Decimal | None) -> str:
    if v is None:
        return ""
    s = f"{v:.2f}"
    whole, frac = s.split(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}{whole}.{frac}"


DESCS = [
    ("UPI/SWIGGY/FOOD ORDER", "w", 350, 900),
    ("SALARY CREDIT ACME PVT LTD", "d", 55000, 55000),
    ("ATM CASH WITHDRAWAL BANER", "w", 2000, 5000),
    ("NEFT/RENT PAYMENT", "w", 15000, 15000),
    ("UPI/BIGBASKET GROCERIES", "w", 800, 2500),
    ("IMPS/REFUND AMAZON", "d", 400, 1500),
    ("ELECTRICITY BILL MSEDCL", "w", 900, 1800),
    ("INTEREST CREDIT", "d", 50, 150),
    ("UPI/PETROL PUMP", "w", 500, 2000),
    ("MOBILE RECHARGE", "w", 299, 699),
]


def make_txns(n: int = 14, start: date = date(2026, 9, 1), seed: int = 7) -> list[Txn]:
    rnd = random.Random(seed)
    out = []
    d = start
    for i in range(n):
        d = d + timedelta(days=rnd.randint(1, 2))
        desc, side, lo, hi = DESCS[i % len(DESCS)] if i else DESCS[1]
        amt = Decimal(rnd.randint(lo * 100, hi * 100)) / 100
        ref = f"TXN{rnd.randint(10**7, 10**8 - 1)}"
        out.append(Txn(d, desc, ref, amt if side == "w" else None, amt if side == "d" else None))
    return out


def build_pdf(
    path: Path | None,
    txns: list[Txn],
    opening: Decimal = Decimal("25000.00"),
    holder: str = "Priya Sharma",
    account: str = "XXXXXXXX1234",
    with_header_row: bool = True,
    tamper_row: int | None = None,
    rows_per_page: int = 9,
    long_desc_row: int | None = 2,
) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    period_start = txns[0].day.replace(day=1)
    period_end = txns[-1].day
    cols = [40, 105, 265, 345, 420, 495]  # date desc ref wd dep bal (right-aligned amounts)

    def page_header(first: bool):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, h - 50, "DEMO BANK LTD - SAMPLE STATEMENT (DUMMY DATA)")
        c.setFont("Helvetica", 10)
        y = h - 80
        if first:
            c.drawString(40, y, f"Account Holder: {holder}")
            c.drawString(320, y, f"Account Number: {account}")
            y -= 16
            c.drawString(40, y, f"Statement Period: {period_start:%d/%m/%Y} to {period_end:%d/%m/%Y}")
            y -= 16
            c.drawString(40, y, "Branch: Baner, Pune")
            y -= 22
            c.drawString(40, y, f"Opening Balance: {inr(opening)}")
            y -= 26
        if with_header_row:
            c.setFont("Helvetica-Bold", 9)
            c.drawString(cols[0], y, "Date")
            c.drawString(cols[1], y, "Description")
            c.drawString(cols[2], y, "Ref No")
            c.drawRightString(cols[3] + 40, y, "Withdrawal")
            c.drawRightString(cols[4] + 40, y, "Deposit")
            c.drawRightString(cols[5] + 55, y, "Balance")
            c.line(40, y - 4, w - 40, y - 4)
            y -= 18
        c.setFont("Helvetica", 9)
        return y

    bal = opening
    y = page_header(True)
    for i, t in enumerate(txns):
        if i and i % rows_per_page == 0:
            c.drawString(40, 40, f"Page {c.getPageNumber()}")
            c.showPage()
            y = page_header(False)
        bal = bal + (t.deposit or 0) - (t.withdrawal or 0)
        shown_bal = bal + Decimal("100.00") if tamper_row == i else bal
        c.drawString(cols[0], y, t.day.strftime("%d/%m/%Y"))
        c.drawString(cols[1], y, t.desc[:28])
        c.drawString(cols[2], y, t.ref)
        c.drawRightString(cols[3] + 40, y, inr(t.withdrawal))
        c.drawRightString(cols[4] + 40, y, inr(t.deposit))
        c.drawRightString(cols[5] + 55, y, inr(shown_bal))
        if long_desc_row == i:
            y -= 12
            c.drawString(cols[1], y, "MONTHLY PAYMENT")
        y -= 16
    y -= 10
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, f"Closing Balance: {inr(bal)}")
    c.setFont("Helvetica", 8)
    c.drawString(40, 40, f"Page {c.getPageNumber()}")
    c.drawString(40, 28, "This is a computer generated dummy statement for testing.")
    c.save()
    data = buf.getvalue()
    if path:
        Path(path).write_bytes(data)
    return data


def rasterize(pdf_bytes: bytes, dpi: int = 200, skew: float = 0.0, noise: bool = True) -> list[Image.Image]:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
        if skew:
            img = img.rotate(skew, expand=True, fillcolor=255)
        if noise:
            img = img.filter(ImageFilter.GaussianBlur(0.6))
        out.append(img)
    return out


def scanned_pdf(pdf_bytes: bytes, path: Path | None = None) -> bytes:
    imgs = rasterize(pdf_bytes, skew=0.3)
    out = pymupdf.open()
    for img in imgs:
        b = io.BytesIO()
        img.save(b, format="JPEG", quality=70)  # scan-like
        page = out.new_page(width=img.width * 72 / 200, height=img.height * 72 / 200)
        page.insert_image(page.rect, stream=b.getvalue())
    data = out.tobytes()
    if path:
        Path(path).write_bytes(data)
    return data


def image_png(pdf_bytes: bytes, path: Path | None = None) -> bytes:
    img = rasterize(pdf_bytes, dpi=200, noise=False)[0]
    b = io.BytesIO()
    img.save(b, format="PNG")
    if path:
        Path(path).write_bytes(b.getvalue())
    return b.getvalue()


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "samples"
    out.mkdir(exist_ok=True)
    txns = make_txns()
    clean = build_pdf(out / "statement_text.pdf", txns)
    build_pdf(out / "statement_tampered.pdf", txns, tamper_row=5)
    build_pdf(out / "statement_full_account_no.pdf", txns, account="123456781234")
    build_pdf(out / "statement_no_table_header.pdf", txns, with_header_row=False)
    scanned_pdf(clean, out / "statement_scanned.pdf")
    single = build_pdf(None, txns[:8], rows_per_page=20)
    image_png(single, out / "statement_image.png")
    print("Samples written to", out)
