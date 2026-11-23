import { Paper, Stack, Typography } from "@mui/material";
import { formatRupees } from "../utils/review";

function Card({ label, hint, value, valueColor, accent, testId }) {
  return (
    <Paper sx={{ p: 2, flex: 1, borderLeft: "4px solid", borderLeftColor: accent }}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h5" sx={{ color: valueColor }} data-testid={testId}>
        {value}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {hint}
      </Typography>
    </Paper>
  );
}

/** Three cards: money in, money out, and what is left. `totals` comes from summarize() in utils/review.js. */
export default function FinancialSummary({ totals, filtered, shown, total }) {
  const { income, expenses, savings, topCategory } = totals;
  const savingsColor = savings < 0 ? "error.main" : "success.main";
  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle2">Smart Financial Summary</Typography>
      <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
        {filtered
          ? `Based on the ${shown} of ${total} transactions that match your filters.`
          : "Based on all transactions below. It updates as you add, edit or delete rows."}
      </Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <Card label="Total Income" hint="Money received (deposits)" value={formatRupees(income)} accent="success.main" testId="summary-income" />
        <Card label="Total Expenses" hint="Money spent (withdrawals)" value={formatRupees(expenses)} accent="warning.main" testId="summary-expenses" />
        <Card
          label="Savings"
          hint="Income minus expenses"
          value={formatRupees(savings)}
          valueColor={savingsColor}
          accent={savingsColor}
          testId="summary-savings"
        />
      </Stack>
      {topCategory && (
        <Typography variant="body2" sx={{ mt: 1.5 }} data-testid="summary-top-category">
          Top Expense Category: <strong>{topCategory.name}</strong> – {formatRupees(topCategory.amount)}
        </Typography>
      )}
    </Paper>
  );
}
