import { Alert, Box, Chip, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { formatAmount } from "../utils/review";

const rupees = (v) => (v === null || v === undefined ? "—" : `₹${formatAmount(v)}`);
const SEVERITY = { high: "error", medium: "warning", low: "info", info: "info" };

function Card({ label, value, hint, id }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5, minWidth: 170, flex: "1 1 170px" }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h6" data-testid={`card-${id}`}>{value}</Typography>
      {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
    </Paper>
  );
}

// Shows the output of /api/analysis or /api/statements/{id}/analytics in plain language.
export default function AnalysisResult({ data }) {
  const a = data.analytics;
  const tamper = data.tamper;
  return (
    <Stack spacing={2} data-testid="analysis-result">
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{data.file_name}</Typography>
        {data.bank && <Chip size="small" label={`Bank: ${data.bank.name}`} />}
        {tamper && (
          <Chip
            size="small"
            data-testid="tamper-chip"
            color={tamper.status === "clean" ? "success" : tamper.status === "suspicious" ? "error" : "default"}
            label={tamper.status === "clean" ? "No edit signs in the file" : tamper.status === "suspicious" ? "Possible tampering" : "File trail not checked"}
          />
        )}
        <Chip size="small" variant="outlined" label={`${a.transaction_count} transactions`} />
      </Stack>

      {data.flags.length > 0 ? (
        <Stack spacing={1} data-testid="flags">
          {data.flags.map((f) => (
            <Alert key={f.code} severity={SEVERITY[f.level] || "info"}>{f.message}</Alert>
          ))}
        </Stack>
      ) : (
        <Alert severity="success">Nothing unusual was found.</Alert>
      )}

      <Box sx={{ display: "flex", gap: 1.5, flexWrap: "wrap" }}>
        <Card id="avg" label="Average daily balance" value={rupees(a.balances?.average_daily_balance)} hint={a.balances ? `Lowest ${rupees(a.balances.min_balance)}` : "No balances in the statement"} />
        <Card id="credits" label="Money in / out" value={`${rupees(a.totals.credits)} / ${rupees(a.totals.debits)}`} hint={`Net ${rupees(a.totals.net)}`} />
        <Card id="salary" label="Salary" value={a.salary.detected ? rupees(a.salary.average_amount) : "Not found"} hint={a.salary.detected ? `${a.salary.months_with_salary} of ${a.salary.months_in_period} months` : null} />
        <Card id="emi" label="Monthly EMI / loan payments" value={rupees(a.emi.monthly_obligation)} hint={a.emi.obligation_to_salary != null ? `${Math.round(a.emi.obligation_to_salary * 100)}% of salary` : null} />
        <Card id="bounces" label="Bounced items" value={a.bounces.count} />
        <Card id="cash" label="Cash deposits" value={rupees(a.cash.deposits_total)} hint={a.cash.large_deposits.length ? `${a.cash.large_deposits.length} large` : null} />
        <Card id="circular" label="Possible circular transfers" value={a.circular.count} />
      </Box>

      {a.monthly.length > 0 && (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" gutterBottom>Month by month</Typography>
          <Table size="small" data-testid="monthly">
            <TableHead>
              <TableRow>
                <TableCell>Month</TableCell>
                <TableCell align="right">Money in</TableCell>
                <TableCell align="right">Money out</TableCell>
                <TableCell align="right">Net</TableCell>
                <TableCell align="right">Average balance</TableCell>
                <TableCell align="right">Lowest balance</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {a.monthly.map((m) => (
                <TableRow key={m.month}>
                  <TableCell>{m.month}</TableCell>
                  <TableCell align="right">{rupees(m.credits)}</TableCell>
                  <TableCell align="right">{rupees(m.debits)}</TableCell>
                  <TableCell align="right">{rupees(m.net)}</TableCell>
                  <TableCell align="right">{rupees(m.average_balance)}</TableCell>
                  <TableCell align="right">{rupees(m.min_balance)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      {a.emi.obligations.length > 0 && (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" gutterBottom>Loan and EMI payments found</Typography>
          {a.emi.obligations.map((e, i) => (
            <Typography key={i} variant="body2">
              {e.narration} · {rupees(e.amount)} · {e.months.join(", ") || "date unknown"} <Typography component="span" variant="caption" color="text.secondary">({e.basis})</Typography>
            </Typography>
          ))}
        </Paper>
      )}

      {a.anomalies?.length > 0 && (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" gutterBottom>Anomalies to review</Typography>
          {a.anomalies.map((item, i) => (
            <Alert key={`${item.code}-${i}`} severity={SEVERITY[item.severity] || "info"} sx={{ mb: 0.5 }}>
              {item.message}
            </Alert>
          ))}
        </Paper>
      )}

      {a.recurring?.length > 0 && (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" gutterBottom>Recurring payments detected</Typography>
          {a.recurring.map((item, i) => (
            <Typography key={i} variant="body2">
              {item.merchant} · {rupees(item.amount)} · {item.count} occurrences · {item.months.join(", ")}
            </Typography>
          ))}
        </Paper>
      )}

      {(a.bounces.count > 0 || a.circular.count > 0 || a.cash.large_deposits.length > 0) && (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="subtitle2" gutterBottom>Rows to look at</Typography>
          {a.bounces.events.map((b) => (
            <Typography key={`b${b.row}`} variant="body2">Row {b.row} · {b.date || "no date"} · bounced/returned · {rupees(b.amount)} · {b.description}</Typography>
          ))}
          {a.cash.large_deposits.map((c) => (
            <Typography key={`c${c.row}`} variant="body2">Row {c.row} · {c.date || "no date"} · large cash deposit · {rupees(c.amount)}</Typography>
          ))}
          {a.circular.pairs.map((p) => (
            <Typography key={`p${p.out_row}`} variant="body2">Rows {p.out_row} and {p.in_row} · {rupees(p.amount)} out and back ({p.party.join(" ")}) after {p.days_apart} day(s)</Typography>
          ))}
        </Paper>
      )}

      <Typography variant="caption" color="text.secondary">
        These are rule-based indicators to help a person decide, not a verdict. {tamper?.note}
      </Typography>
    </Stack>
  );
}
