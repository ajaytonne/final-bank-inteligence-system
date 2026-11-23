export const MAX_UPLOAD_MB = 10;
export const ACCEPTED_EXT = [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"];
export const HEADER_FIELDS = [
  { key: "bank_name", label: "Bank name", type: "text" },
  { key: "branch_name", label: "Branch", type: "text" },
  { key: "account_holder", label: "Account holder", type: "text" },
  { key: "account_number_masked", label: "Account number (masked)", type: "text" },
  { key: "account_type", label: "Account type", type: "text" },
  { key: "ifsc", label: "IFSC", type: "text" },
  { key: "currency", label: "Currency", type: "select", options: ["INR", "USD", "EUR", "GBP", "AED", "SGD", "CAD", "AUD", "JPY"] },
  { key: "period_start", label: "Period start", type: "date" },
  { key: "period_end", label: "Period end", type: "date" },
  { key: "opening_balance", label: "Opening balance", type: "amount" },
  { key: "closing_balance", label: "Closing balance", type: "amount" },
];
export const TXN_FIELDS = ["date", "effective_date", "description", "reference", "withdrawal", "deposit", "balance"];
const AMOUNT_RE = /^-?\d+(\.\d{1,2})?$/;

export function validateClientFile(file) {
  if (!file) return "Choose a file to upload.";
  const name = file.name.toLowerCase();
  const ext = name.includes(".") ? name.slice(name.lastIndexOf(".")) : "";
  if (!ACCEPTED_EXT.includes(ext)) return `Unsupported file type. Allowed: ${ACCEPTED_EXT.join(", ")}`;
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `File exceeds ${MAX_UPLOAD_MB} MB.`;
  return null;
}

export function confidenceLevel(conf) {
  if (conf >= 0.85) return "high";
  if (conf >= 0.75) return "medium";
  return "low";
}

export function formatAmount(v) {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const toStr = (v) => (v === null || v === undefined ? "" : String(v));

function editable(field) {
  return {
    value: toStr(field?.value),
    original: toStr(field?.value),
    confidence: field?.confidence ?? 0,
    needsReview: Boolean(field?.needs_review),
    source: field?.source ?? "none",
    note: field?.note ?? null,
  };
}

let rowSeq = 0;
export function toReviewState(result) {
  const header = {};
  HEADER_FIELDS.forEach(({ key }) => {
    header[key] = key === "currency" && !result.header[key]
      ? editable({ value: "INR", confidence: 1, needs_review: false, source: "derived" })
      : editable(result.header[key]);
  });
  const rows = result.transactions.map((t) => {
    const row = { id: `r${rowSeq++}`, page: t.page, confidence: t.confidence, issues: t.issues, needsReview: t.needs_review, acknowledged: false, added: false };
    TXN_FIELDS.forEach((k) => (row[k] = editable(t[k])));
    row.category = detectCategory(row.description.value);
    row.categoryManual = false;
    return row;
  });
  return { fileName: result.file_name, extractionMethod: result.method || "none", header, headerAck: {}, rows };
}

export function emptyRow() {
  const row = { id: `r${rowSeq++}`, page: null, confidence: 1, issues: [], needsReview: true, acknowledged: false, added: true, category: "Other", categoryManual: false };
  TXN_FIELDS.forEach((k) => (row[k] = { value: "", original: "", confidence: 1, needsReview: false, source: "user", note: null }));
  return row;
}

export function fieldError(type, value) {
  if (value === "") return null;
  if (type === "select" && !HEADER_FIELDS.find((f) => f.type === "select")?.options.includes(value)) return "Choose a supported currency code";
  if (type === "amount" && !AMOUNT_RE.test(value.replace(/,/g, ""))) return "Use a number like 1250.00";
  if (type === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Use YYYY-MM-DD";
  return null;
}

export function txnFieldType(key) {
  if (["date", "effective_date"].includes(key)) return "date";
  if (["withdrawal", "deposit", "balance"].includes(key)) return "amount";
  return "text";
}

export function rowErrors(row) {
  const errs = [];
  TXN_FIELDS.forEach((k) => {
    const e = fieldError(txnFieldType(k), row[k].value);
    if (e) errs.push(`${k}: ${e}`);
  });
  if (row.deposit.value && row.withdrawal.value && Number(row.deposit.value) && Number(row.withdrawal.value)) {
    errs.push("Row has both deposit and withdrawal");
  }
  if (!row.date.value) errs.push("date: required");
  return errs;
}

const num = (s) => (s === "" ? null : Number(String(s).replace(/,/g, "")));

/** Live balance check on edited values. */
export function checkBalances(state) {
  let prev = num(state.header.opening_balance.value);
  const mismatched = new Set();
  state.rows.forEach((r) => {
    const dep = num(r.deposit.value) || 0;
    const wd = num(r.withdrawal.value) || 0;
    const bal = num(r.balance.value);
    if (prev !== null && bal !== null && Math.abs(prev + dep - wd - bal) > 0.009) mismatched.add(r.id);
    if (bal !== null) prev = bal;
    else if (prev !== null) prev = prev + dep - wd;
  });
  const closing = num(state.header.closing_balance.value);
  const closingOk = closing === null || prev === null || Math.abs(prev - closing) <= 0.009;
  return { mismatched, computedClosing: prev, closingOk };
}

export function openReviewItems(state) {
  const items = [];
  HEADER_FIELDS.forEach(({ key, label }) => {
    if (state.header[key].needsReview && !state.headerAck[key]) items.push({ kind: "header", key, label });
  });
  state.rows.forEach((r, i) => {
    if (r.needsReview && !r.acknowledged) items.push({ kind: "row", key: r.id, label: `Row ${i + 1}` });
  });
  return items;
}

export function validationErrors(state) {
  const errs = [];
  HEADER_FIELDS.forEach(({ key, label, type }) => {
    const e = fieldError(type, state.header[key].value);
    if (e) errs.push(`${label}: ${e}`);
  });
  const acct = state.header.account_number_masked.value;
  if ((acct.match(/\d/g) || []).length > 4) errs.push("Account number must show at most 4 digits");
  const { period_start: ps, period_end: pe } = state.header;
  if (ps.value && pe.value && ps.value > pe.value) errs.push("Period start is after period end");
  state.rows.forEach((r, i) => rowErrors(r).forEach((e) => errs.push(`Row ${i + 1} ${e}`)));
  return errs;
}

const clean = (s) => {
  const t = (s ?? "").trim();
  return t === "" ? null : t;
};
const cleanAmt = (s) => {
  const t = clean(s);
  return t === null ? null : t.replace(/,/g, "");
};

export function buildSavePayload(state, reviewerNote = "") {
  const h = state.header;
  const confidenceFields = [
    ...HEADER_FIELDS.map(({ key }) => h[key]),
    ...state.rows.flatMap((row) => TXN_FIELDS.map((key) => row[key])),
  ].filter((field) => field && ["pdf_text", "ocr", "llm", "derived"].includes(field.source));
  const sourceCount = (source) => confidenceFields.filter((field) => field.source === source).length;
  return {
    file_name: state.fileName,
    review_metadata: {
      extraction_method: state.extractionMethod || "none",
      average_confidence: confidenceFields.length
        ? confidenceFields.reduce((total, field) => total + field.confidence, 0) / confidenceFields.length
        : 0,
      field_count: confidenceFields.length,
      ocr_field_count: sourceCount("ocr"),
      pdf_text_field_count: sourceCount("pdf_text"),
      derived_field_count: sourceCount("derived"),
      low_confidence_field_count: confidenceFields.filter((field) => field.needsReview || field.confidence < 0.75).length,
    },
    header: {
      bank_name: clean(h.bank_name.value),
      branch_name: clean(h.branch_name.value),
      account_holder: clean(h.account_holder.value),
      account_number_masked: clean(h.account_number_masked.value),
      account_type: clean(h.account_type.value),
      ifsc: clean(h.ifsc.value),
      currency: clean(h.currency.value) || "INR",
      period_start: clean(h.period_start.value),
      period_end: clean(h.period_end.value),
      opening_balance: cleanAmt(h.opening_balance.value),
      closing_balance: cleanAmt(h.closing_balance.value),
    },
    transactions: state.rows.map((r) => ({
      date: clean(r.date.value),
      effective_date: clean(r.effective_date.value),
      description: clean(r.description.value),
      reference: clean(r.reference.value),
      withdrawal: cleanAmt(r.withdrawal.value),
      deposit: cleanAmt(r.deposit.value),
      balance: cleanAmt(r.balance.value),
      category: r.category,
    })),
    reviewer_note: clean(reviewerNote),
    changes: buildChanges(state),
  };
}

/** What the reviewer edited (value differs from what was extracted). Goes to the audit trail only. */
export function buildChanges(state) {
  const changes = [];
  HEADER_FIELDS.forEach(({ key, label }) => {
    const f = state.header[key];
    if (f.value !== f.original) changes.push({ where: "Header", field: label, old: clean(f.original), new: clean(f.value) });
  });
  state.rows.forEach((r, i) => {
    const where = `Row ${i + 1}`;
    if (r.added) {
      changes.push({ where, field: "row", old: null, new: "added by reviewer" });
      return;
    }
    TXN_FIELDS.forEach((k) => {
      if (r[k].value !== r[k].original) changes.push({ where, field: k, old: clean(r[k].original), new: clean(r[k].value) });
    });
  });
  return changes.slice(0, 2000);
}

// ---- Categories, filters and the financial summary ----------------------------------------

// Keep in sync with Category in backend/app/schemas.py
// Categories used when identifying merchants. Keep in sync with MerchantCategory in backend/app/schemas.py
export const MERCHANT_CATEGORIES = ["Shopping", "Food", "Groceries", "Transport", "Utilities", "Entertainment", "Banking", "Other"];

export const CATEGORIES = ["Food", "Shopping", "Salary", "Bills", "Transport", "Entertainment", "Health", "Education", "Other"];

// The first category whose keyword appears in the description wins (top to bottom).
const KEYWORDS = {
  Food: ["zomato", "swiggy", "restaurant", "food", "grocery", "groceries", "pizza", "cafe"],
  Shopping: ["amazon", "flipkart", "myntra", "shopping", "clothes", "shoes"],
  Salary: ["salary", "monthly income", "freelance", "payment received", "stipend"],
  Bills: ["electricity", "water bill", "rent", "internet", "recharge", "mobile bill"],
  Transport: ["uber", "ola", "petrol", "diesel", "bus", "train", "metro", "fuel"],
  Entertainment: ["movie", "netflix", "prime video", "game", "concert"],
  Health: ["medicine", "hospital", "doctor", "pharmacy", "clinic"],
  Education: ["college", "school", "course", "book", "exam fee", "tuition"],
};
// Whole words only (letters on both sides don't count), so "rent" matches "NEFT/RENT PAYMENT"
// but not "current account", and "bus" does not match "business". A trailing "s" is allowed.
const RULES = Object.entries(KEYWORDS).map(([name, words]) => [name, new RegExp(`(?:^|[^a-z])(?:${words.join("|")})s?(?:$|[^a-z])`, "i")]);

export function detectCategory(description) {
  const text = String(description || "").replace(/\s+/g, " ");
  return RULES.find(([, re]) => re.test(text))?.[0] || "Other";
}

// Valid positive amount from a text field, otherwise 0.
const amountOf = (s) => {
  const n = Number(String(s ?? "").replace(/,/g, ""));
  return n > 0 ? n : 0;
};

/** A deposit is Income, a withdrawal is an Expense. */
export function rowType(row) {
  if (amountOf(row.deposit.value) > 0) return "Income";
  if (amountOf(row.withdrawal.value) > 0) return "Expense";
  return "";
}

export const EMPTY_FILTERS = { search: "", from: "", to: "", min: "", max: "", type: "All", category: "All" };

export const hasFilters = (f) => Object.keys(EMPTY_FILTERS).some((k) => f[k] !== EMPTY_FILTERS[k]);

const optionalNumber = (s) => {
  const n = String(s).trim() === "" ? NaN : Number(String(s).replace(/,/g, ""));
  return Number.isNaN(n) ? null : n;
};

/** Keeps the rows that match every filter that is set. */
export function filterRows(rows, f) {
  const search = f.search.trim().toLowerCase();
  const min = optionalNumber(f.min);
  const max = optionalNumber(f.max);
  return rows.filter((r) => {
    if (search && !r.description.value.toLowerCase().includes(search)) return false;
    const date = r.date.value; // YYYY-MM-DD, so plain string comparison works
    if (f.from && !(date && date >= f.from)) return false;
    if (f.to && !(date && date <= f.to)) return false;
    const amount = amountOf(r.deposit.value) || amountOf(r.withdrawal.value);
    if (min !== null && amount < min) return false;
    if (max !== null && amount > max) return false;
    if (f.type !== "All" && rowType(r) !== f.type) return false;
    if (f.category !== "All" && r.category !== f.category) return false;
    return true;
  });
}

/** Income, expenses, savings and the biggest expense category (summed in paise to avoid float drift). */
export function summarize(rows) {
  let income = 0;
  let expenses = 0;
  const byCategory = {};
  rows.forEach((r) => {
    const deposit = Math.round(amountOf(r.deposit.value) * 100);
    const withdrawal = Math.round(amountOf(r.withdrawal.value) * 100);
    income += deposit;
    expenses += withdrawal;
    if (withdrawal > 0) byCategory[r.category] = (byCategory[r.category] || 0) + withdrawal;
  });
  const top = Object.entries(byCategory).sort((a, b) => b[1] - a[1])[0];
  return {
    income: income / 100,
    expenses: expenses / 100,
    savings: (income - expenses) / 100,
    topCategory: top ? { name: top[0], amount: top[1] / 100 } : null,
  };
}

export const formatRupees = (n) => `${n < 0 ? "-" : ""}₹${formatAmount(Math.abs(n))}`;
