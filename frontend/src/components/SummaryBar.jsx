import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { formatAmount } from "../utils/review";

const METHOD_LABEL = { pdf_text: "PDF text", ocr: "OCR", mixed: "PDF text + OCR", none: "No text" };

export default function SummaryBar({ result, live, openCount }) {
  const [showRaw, setShowRaw] = useState(false);
  const balanceOk = live.mismatched.size === 0 && live.closingOk;
  const rows = result.transactions || [];
  const totalIncome = rows.reduce((sum, row) => sum + Number(row.deposit?.value || 0), 0);
  const totalExpenses = rows.reduce((sum, row) => sum + Number(row.withdrawal?.value || 0), 0);
  const categoryRules = [
    ["Transfers", /upi|imps|neft|rtgs|transfer|funding/i],
    ["Food", /food|restaurant|cafe|swiggy|zomato/i],
    ["Shopping", /amazon|flipkart|retail|shop|mart/i],
    ["Bills", /bill|electric|recharge|utility|gas|water/i],
    ["Fees", /charge|fee|gst|tax/i],
  ];
  const categories = {};
  const months = {};
  const seen = new Map();
  const duplicates = [];
  const expenses = [];
  rows.forEach((row) => {
    const amount = Number(row.withdrawal?.value || 0);
    const description = row.description?.value || "";
    if (amount > 0) {
      const category = categoryRules.find(([, pattern]) => pattern.test(description))?.[0] || "Other";
      categories[category] = (categories[category] || 0) + amount;
      expenses.push(amount);
    }
    const month = String(row.date?.value || "").slice(0, 7);
    if (month) {
      months[month] ||= { income: 0, expenses: 0 };
      months[month].income += Number(row.deposit?.value || 0);
      months[month].expenses += amount;
    }
    const key = [row.date?.value, description.trim().toLowerCase(), row.deposit?.value || "", row.withdrawal?.value || ""].join("|");
    if (description && (Number(row.deposit?.value || 0) || amount)) {
      if (seen.has(key)) duplicates.push([seen.get(key), row]); else seen.set(key, row);
    }
  });
  const sortedExpenses = [...expenses].sort((a, b) => a - b);
  const median = sortedExpenses.length ? sortedExpenses[Math.floor(sortedExpenses.length / 2)] : 0;
  const unusual = median ? rows.filter((row) => Number(row.withdrawal?.value || 0) >= Math.max(10000, median * 3)) : [];
  const amountText = (v) => formatAmount(v.toFixed(2));
  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ md: "center" }} flexWrap="wrap" useFlexGap>
        <Typography variant="subtitle2" sx={{ mr: 1 }}>
          {result.file_name}
        </Typography>
        <Chip size="small" label={`${METHOD_LABEL[result.method]} · ${result.page_count} page(s)`} />
        {result.ocr_pages.length > 0 && <Chip size="small" label={`OCR pages: ${result.ocr_pages.join(", ")}`} />}
        {result.llm_used && <Chip size="small" color="secondary" label="Local LLM assisted" />}
        <Chip
          size="small"
          color={balanceOk ? "success" : "warning"}
          label={balanceOk ? "Running balance consistent" : `Balance issues: ${live.mismatched.size} row(s)${live.closingOk ? "" : " + closing"}`}
          data-testid="balance-chip"
        />
        <Chip
          size="small"
          color={openCount ? "warning" : "success"}
          variant={openCount ? "filled" : "outlined"}
          label={openCount ? `${openCount} item(s) to review` : "All flagged items reviewed"}
          data-testid="review-chip"
        />
        <Box sx={{ flexGrow: 1 }} />
        <Button size="small" onClick={() => setShowRaw(true)}>
          View extracted text
        </Button>
      </Stack>
      {live.computedClosing !== null && (
        <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 1 }}>
          Computed closing balance: {formatAmount(live.computedClosing)} · {result.confidence_note}
        </Typography>
      )}
      <details style={{ marginTop: 12 }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>Statement analysis</summary>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
          <Chip size="small" label={`Income: ₹${amountText(totalIncome)}`} color="success" variant="outlined" />
          <Chip size="small" label={`Expenses: ₹${amountText(totalExpenses)}`} color="warning" variant="outlined" />
          <Chip size="small" label={`Opening: ₹${formatAmount(stateAmount(result.header.opening_balance)) || "—"}`} />
          <Chip size="small" label={`Closing: ₹${formatAmount(stateAmount(result.header.closing_balance)) || "—"}`} />
          <Chip size="small" label={`Possible duplicates: ${duplicates.length}`} color={duplicates.length ? "warning" : "default"} />
          <Chip size="small" label={`Unusual debits: ${unusual.length}`} color={unusual.length ? "warning" : "default"} />
        </Stack>
        <Typography variant="body2" sx={{ mt: 1 }}>
          Spending categories: {Object.entries(categories).map(([name, value]) => `${name} ₹${amountText(value)}`).join(" · ") || "No debit transactions"}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Monthly income / expense: {Object.entries(months).sort(([a], [b]) => a.localeCompare(b)).map(([month, v]) => `${month}: ₹${amountText(v.income)} / ₹${amountText(v.expenses)}`).join(" · ") || "No dated transactions"}
        </Typography>
        {(duplicates.length > 0 || unusual.length > 0) && (
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
            Review possible duplicates and unusually large debits against the original statement.
          </Typography>
        )}
      </details>
      {result.warnings.map((w) => (
        <Alert key={w} severity="warning" sx={{ mt: 1, py: 0 }}>
          {w}
        </Alert>
      ))}
      <Dialog open={showRaw} onClose={() => setShowRaw(false)} maxWidth="md" fullWidth>
        <DialogTitle>Extracted text (account numbers redacted)</DialogTitle>
        <DialogContent>
          <Box component="pre" sx={{ fontSize: 12, whiteSpace: "pre-wrap", m: 0 }}>
            {result.raw_text || "(no text)"}
          </Box>
        </DialogContent>
      </Dialog>
    </Paper>
  );
}

function stateAmount(field) {
  return field?.value ?? null;
}
