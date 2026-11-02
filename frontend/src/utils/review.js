export const MAX_UPLOAD_MB = 10;
export const ACCEPTED_EXT = [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"];
export const HEADER_FIELDS = [
  { key: "bank_name", label: "Bank name", type: "text" },
  { key: "branch_name", label: "Branch", type: "text" },
  { key: "account_holder", label: "Account holder", type: "text" },
  { key: "account_number_masked", label: "Account number (masked)", type: "text" },
  { key: "account_type", label: "Account type", type: "text" },
  { key: "ifsc", label: "IFSC", type: "text" },
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
  HEADER_FIELDS.forEach(({ key }) => (header[key] = editable(result.header[key])));
  const rows = result.transactions.map((t) => {
    const row = { id: `r${rowSeq++}`, page: t.page, confidence: t.confidence, issues: t.issues, needsReview: t.needs_review, acknowledged: false, added: false };
    TXN_FIELDS.forEach((k) => (row[k] = editable(t[k])));
    return row;
  });
  return { fileName: result.file_name, header, headerAck: {}, rows };
}

export function emptyRow() {
  const row = { id: `r${rowSeq++}`, page: null, confidence: 1, issues: [], needsReview: true, acknowledged: false, added: true };
  TXN_FIELDS.forEach((k) => (row[k] = { value: "", original: "", confidence: 1, needsReview: false, source: "user", note: null }));
  return row;
}

export function fieldError(type, value) {
  if (value === "") return null;
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
  return {
    file_name: state.fileName,
    header: {
      bank_name: clean(h.bank_name.value),
      branch_name: clean(h.branch_name.value),
      account_holder: clean(h.account_holder.value),
      account_number_masked: clean(h.account_number_masked.value),
      account_type: clean(h.account_type.value),
      ifsc: clean(h.ifsc.value),
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
    })),
    reviewer_note: clean(reviewerNote),
  };
}
