import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, Box, Button, Chip, IconButton, Link, Paper, Stack, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DownloadIcon from "@mui/icons-material/Download";
import AccountBalanceWalletOutlinedIcon from "@mui/icons-material/AccountBalanceWalletOutlined";
import TrendingUpOutlinedIcon from "@mui/icons-material/TrendingUpOutlined";
import TrendingDownOutlinedIcon from "@mui/icons-material/TrendingDownOutlined";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import RepeatOutlinedIcon from "@mui/icons-material/RepeatOutlined";
import { api } from "../api/client";

const CHART_COLORS = ["#0f766e", "#2563eb", "#7c3aed", "#ea580c", "#db2777", "#0891b2", "#65a30d"];

function Metric({ label, value, tone, icon: Icon, accent = "#0f766e" }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, flex: "1 1 175px", minWidth: 0, position: "relative", overflow: "hidden" }}>
      <Box sx={{ position: "absolute", right: -14, top: -16, color: accent, opacity: 0.1, transform: "rotate(-12deg)" }}>
        {Icon && <Icon sx={{ fontSize: 84 }} />}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ position: "relative" }}>{label}</Typography>
      <Typography variant="h6" color={tone} sx={{ overflowWrap: "anywhere", position: "relative", mt: 0.5 }}>{value}</Typography>
    </Paper>
  );
}

function money(amount, currency) {
  const value = Number(amount || 0);
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, minimumFractionDigits: 2 }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

function MonthlyChart({ data, currency }) {
  const rows = data.filter((row) => row.currency === currency).slice(-6);
  if (!rows.length) return null;
  const width = 720;
  const height = 250;
  const left = 56;
  const right = 18;
  const top = 18;
  const bottom = 38;
  const chartHeight = height - top - bottom;
  const chartWidth = width - left - right;
  const max = Math.max(1, ...rows.flatMap((row) => [row.credits, row.debits]));
  const slot = chartWidth / rows.length;
  const barWidth = Math.min(28, slot * 0.27);
  const ticks = [0, 1, 2, 3].map((i) => max * i / 3);
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>{currency}</Typography>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Monthly income and spending in ${currency}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {ticks.map((tick, i) => {
          const y = top + chartHeight * (1 - i / 3);
          return (
            <g key={i}>
              <line x1={left} x2={width - right} y1={y} y2={y} stroke="#e8edf2" />
              <text x={left - 8} y={y + 4} textAnchor="end" fill="#728096" fontSize="10">
                {tick >= 1000000 ? `${(tick / 1000000).toFixed(1)}m` : tick >= 1000 ? `${Math.round(tick / 1000)}k` : Math.round(tick)}
              </text>
            </g>
          );
        })}
        {rows.map((row, i) => {
          const center = left + slot * (i + 0.5);
          const creditHeight = row.credits / max * chartHeight;
          const debitHeight = row.debits / max * chartHeight;
          return (
            <g key={row.month}>
              <rect x={center - barWidth - 2} y={top + chartHeight - creditHeight} width={barWidth} height={creditHeight} rx="5" fill="#0f766e">
                <title>{row.month} income: {money(row.credits, currency)}</title>
              </rect>
              <rect x={center + 2} y={top + chartHeight - debitHeight} width={barWidth} height={debitHeight} rx="5" fill="#f97366">
                <title>{row.month} spending: {money(row.debits, currency)}</title>
              </rect>
              <text x={center} y={height - 13} textAnchor="middle" fill="#65748b" fontSize="11">{row.month.slice(5)}</text>
            </g>
          );
        })}
      </svg>
    </Box>
  );
}

function CategoryChart({ categories, currency }) {
  const values = categories.filter((item) => item.currency === currency && item.amount > 0);
  const total = values.reduce((sum, item) => sum + item.amount, 0);
  if (!total) return <Typography variant="body2" color="text.secondary">No expense categories found.</Typography>;
  const circumference = 2 * Math.PI * 43;
  let offset = 0;
  const segments = values.map((item, index) => {
    const length = item.amount / total * circumference;
    const segment = { ...item, color: CHART_COLORS[index % CHART_COLORS.length], length, offset };
    offset += length;
    return segment;
  });
  return (
    <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems="center">
      <Box sx={{ width: 190, maxWidth: "100%", flex: "0 0 auto" }}>
        <svg viewBox="0 0 120 120" role="img" aria-label={`Expense categories in ${currency}`} style={{ width: "100%", display: "block" }}>
          <circle cx="60" cy="60" r="43" fill="none" stroke="#edf1f5" strokeWidth="17" />
          {segments.map((item) => (
            <circle
              key={item.category}
              cx="60" cy="60" r="43" fill="none" stroke={item.color} strokeWidth="17"
              strokeDasharray={`${item.length} ${circumference - item.length}`}
              strokeDashoffset={-item.offset}
              transform="rotate(-90 60 60)"
            >
              <title>{item.category}: {money(item.amount, currency)}</title>
            </circle>
          ))}
          <text x="60" y="56" textAnchor="middle" fill="#728096" fontSize="8">TOTAL SPEND</text>
          <text x="60" y="68" textAnchor="middle" fill="#182230" fontSize="9" fontWeight="700">{money(total, currency)}</text>
        </svg>
      </Box>
      <Stack spacing={0.75} sx={{ width: "100%" }}>
        {segments.slice(0, 7).map((item) => (
          <Stack key={item.category} direction="row" spacing={1} alignItems="center">
            <Box sx={{ width: 9, height: 9, borderRadius: "50%", bgcolor: item.color, flex: "0 0 auto" }} />
            <Typography variant="body2" sx={{ flexGrow: 1 }}>{item.category}</Typography>
            <Typography variant="caption" color="text.secondary">{Math.round(item.amount / total * 100)}%</Typography>
            <Typography variant="body2" sx={{ minWidth: 90, textAlign: "right" }}>{money(item.amount, currency)}</Typography>
          </Stack>
        ))}
      </Stack>
    </Stack>
  );
}

export default function Dashboard({ onNavigate = () => {} }) {
  const [items, setItems] = useState([]);
  const [rules, setRules] = useState([]);
  const [error, setError] = useState(null);
  const [rulesError, setRulesError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyRule, setBusyRule] = useState(null);
  const [reload, setReload] = useState(0);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const saved = await api.list();
      const rows = await Promise.all(saved.map(async (statement) => {
        const [detail, report] = await Promise.allSettled([
          api.get(statement.id),
          api.savedAnalytics(statement.id),
        ]);
        return {
          statement,
          currency: detail.status === "fulfilled" ? detail.value.statement.header.currency || "INR" : "INR",
          reviewMetadata: detail.status === "fulfilled" ? detail.value.statement.review_metadata || null : null,
          transactions: detail.status === "fulfilled" ? detail.value.statement.transactions || [] : [],
          analytics: report.status === "fulfilled" ? report.value.analytics : null,
          analyticsError: report.status === "rejected" ? report.reason.message : null,
          currencyError: detail.status === "rejected" ? detail.reason.message : null,
        };
      }));
      setItems(rows);
      const failed = rows.filter((row) => row.analyticsError || row.currencyError).length;
      if (failed) setError(`${failed} statement detail or analysis request${failed === 1 ? "" : "s"} failed. Other results are still shown.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshRules = useCallback(async () => {
    setRulesError(null);
    try {
      setRules(await api.listMerchantMappings());
    } catch (e) {
      setRulesError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, reload]);

  useEffect(() => {
    refreshRules();
  }, [refreshRules]);

  const byCurrency = useMemo(() => {
    const groups = new Map();
    items.forEach(({ analytics, currency }) => {
      if (!analytics) return;
      const group = groups.get(currency) || { currency, credits: 0, debits: 0 };
      group.credits += Number(analytics.totals?.credits || 0);
      group.debits += Number(analytics.totals?.debits || 0);
      groups.set(currency, group);
    });
    return [...groups.values()].sort((a, b) => a.currency.localeCompare(b.currency));
  }, [items]);

  const anomalyRows = useMemo(() => items.flatMap(({ statement, analytics, currency }) =>
    (analytics?.anomalies || []).map((anomaly, i) => ({ ...anomaly, currency, statementId: statement.id, fileName: statement.file_name, key: `${statement.id}-${anomaly.code}-${anomaly.row || anomaly.month || i}` }))
  ), [items]);

  const recurringRows = useMemo(() => items.flatMap(({ statement, analytics, currency }) =>
    (analytics?.recurring || []).map((payment, i) => ({ ...payment, currency, fileName: statement.file_name, key: `${statement.id}-${payment.merchant}-${i}` }))
  ), [items]);

  const monthlyGroups = useMemo(() => {
    const groups = new Map();
    items.forEach(({ analytics, currency }) => {
      (analytics?.monthly || []).forEach((month) => {
        const key = `${currency}-${month.month}`;
        const item = groups.get(key) || { currency, month: month.month, credits: 0, debits: 0 };
        item.credits += Number(month.credits || 0);
        item.debits += Number(month.debits || 0);
        groups.set(key, item);
      });
    });
    return [...groups.values()].sort((a, b) => a.month.localeCompare(b.month) || a.currency.localeCompare(b.currency));
  }, [items]);

  const categoryGroups = useMemo(() => {
    const groups = new Map();
    items.forEach(({ transactions, currency }) => {
      transactions.forEach((transaction) => {
        const amount = Number(transaction.withdrawal || 0);
        if (amount <= 0) return;
        const category = transaction.category || "Other";
        const key = `${currency}-${category}`;
        const group = groups.get(key) || { currency, category, amount: 0 };
        group.amount += amount;
        groups.set(key, group);
      });
    });
    return [...groups.values()].sort((a, b) => b.amount - a.amount);
  }, [items]);

  const removeRule = async (id) => {
    setBusyRule(id);
    setRulesError(null);
    try {
      await api.removeMerchantMapping(id);
      await refreshRules();
    } catch (e) {
      setRulesError(e.message);
    } finally {
      setBusyRule(null);
    }
  };

  const onExport = (id) => api.statementExportUrl(id);
  const successful = items.filter((item) => item.analytics);
  const anomalyCount = successful.reduce((total, item) => total + (item.analytics.anomalies?.length || 0), 0);
  const recurringCount = successful.reduce((total, item) => total + (item.analytics.recurring?.length || 0), 0);
  const qualityFields = items.reduce((total, item) => total + (item.reviewMetadata?.field_count || 0), 0);
  const averageConfidence = qualityFields
    ? items.reduce((total, item) => total + (item.reviewMetadata?.average_confidence || 0) * (item.reviewMetadata?.field_count || 0), 0) / qualityFields
    : null;
  const ocrFieldCount = items.reduce((total, item) => total + (item.reviewMetadata?.ocr_field_count || 0), 0);

  return (
    <Stack spacing={2} data-testid="dashboard">
      <Paper sx={{
        p: { xs: 2.5, md: 3.5 }, color: "#fff", border: 0,
        background: "linear-gradient(115deg, #10243a 0%, #124b58 55%, #0f766e 100%)",
      }}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
          <Box sx={{ flexGrow: 1 }}>
            <Typography variant="overline" sx={{ letterSpacing: 1.5, color: "#a9e3d4" }}>STATEMENT INSIGHTS</Typography>
            <Typography variant="h4" sx={{ fontWeight: 700, lineHeight: 1.15, fontSize: { xs: 27, sm: 34 } }}>Your money, in perspective</Typography>
            <Typography variant="body2" sx={{ color: "rgba(255,255,255,0.78)", mt: 0.75 }}>
              Cash flow, spending patterns, and review signals from your saved statements.
            </Typography>
          </Box>
          <Button
            variant="outlined"
            onClick={() => setReload((n) => n + 1)}
            disabled={loading}
            sx={{ color: "#fff", borderColor: "rgba(255,255,255,0.55)", "&:hover": { borderColor: "#fff", bgcolor: "rgba(255,255,255,0.08)" } }}
          >
            Refresh dashboard
          </Button>
        </Stack>
      </Paper>

      {error && <Alert severity="error" action={<Button color="inherit" size="small" onClick={() => setReload((n) => n + 1)}>Retry</Button>}>{error}</Alert>}
      {loading && <Alert severity="info">Loading saved statements and analytics…</Alert>}

      {!loading && items.length === 0 && (
        <Paper sx={{ p: { xs: 2, sm: 4 } }}>
          <Typography variant="h6" gutterBottom>Your dashboard is ready for statements</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            There are no saved statements in this local database yet. Upload a statement, verify the extracted fields, then choose “Save reviewed data.” Dashboard totals will appear here after saving.
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button variant="contained" color="secondary" onClick={() => onNavigate("review")}>Review a statement</Button>
            <Button variant="outlined" onClick={() => onNavigate("analysis")}>Analyse a statement</Button>
            <Button variant="outlined" onClick={() => onNavigate("reconcile")}>Compare statements</Button>
          </Stack>
        </Paper>
      )}

      {items.length > 0 && (
        <>
          <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", sm: "repeat(auto-fit, minmax(175px, 1fr))" } }}>
            <Metric label="Saved statements" value={items.length} icon={AccountBalanceWalletOutlinedIcon} accent="#2563eb" />
            <Metric label="Anomalies to review" value={anomalyCount} tone={anomalyCount ? "warning.main" : undefined} icon={WarningAmberOutlinedIcon} accent="#d97706" />
            <Metric label="Recurring payments" value={recurringCount} icon={RepeatOutlinedIcon} accent="#7c3aed" />
            <Metric label="Average extraction score" value={averageConfidence === null ? "Not recorded" : `${Math.round(averageConfidence * 100)}%`} icon={TrendingUpOutlinedIcon} accent="#0f766e" />
          </Box>
          <Typography variant="caption" color="text.secondary">
            {ocrFieldCount} OCR-extracted fields · {rules.length} saved merchant corrections. Extraction scores are heuristic review signals, not probabilities.
          </Typography>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle1" gutterBottom>Cash flow by currency</Typography>
            <Typography variant="caption" color="text.secondary">
              Totals sum the transactions in saved statements; overlapping statement periods can count the same transaction more than once. Amounts are not converted between currencies.
            </Typography>
            {byCurrency.length === 0 ? (
              <Alert severity="warning" sx={{ mt: 1 }}>Statement totals could not be loaded. Use Refresh dashboard to try again.</Alert>
            ) : (
              <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", md: `repeat(${Math.min(byCurrency.length, 2)}, minmax(0, 1fr))` }, mt: 1.5 }}>
                {byCurrency.map(({ currency, credits, debits }) => (
                  <Paper key={currency} variant="outlined" sx={{ p: 2, background: "linear-gradient(135deg, #f8fbff 0%, #fff 70%)" }}>
                    <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
                      <Chip size="small" label={currency} color="secondary" variant="outlined" />
                      <Typography variant="caption" color="text.secondary">Across saved statements</Typography>
                    </Stack>
                    <Box sx={{ display: "grid", gap: 1, gridTemplateColumns: { xs: "1fr", sm: "repeat(3, minmax(0, 1fr))" } }}>
                      <Metric label="Income" value={money(credits, currency)} tone="success.main" icon={TrendingUpOutlinedIcon} accent="#0f766e" />
                      <Metric label="Spending" value={money(debits, currency)} tone="error.main" icon={TrendingDownOutlinedIcon} accent="#dc2626" />
                      <Metric label="Net cash flow" value={money(credits - debits, currency)} tone={credits >= debits ? "success.main" : "error.main"} icon={AccountBalanceWalletOutlinedIcon} accent="#2563eb" />
                    </Box>
                  </Paper>
                ))}
              </Box>
            )}
          </Paper>

          {monthlyGroups.length > 0 && (
            <Paper sx={{ p: 2 }}>
              <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} spacing={1} sx={{ mb: 1 }}>
                <Box sx={{ flexGrow: 1 }}>
                  <Typography variant="subtitle1">Monthly cash flow</Typography>
                  <Typography variant="caption" color="text.secondary">Income and spending by statement month</Typography>
                </Box>
                <Stack direction="row" spacing={1}>
                  <Chip size="small" label="Income" sx={{ bgcolor: "#e5f4ef", color: "#0f766e" }} />
                  <Chip size="small" label="Spending" sx={{ bgcolor: "#fff0ed", color: "#c24135" }} />
                </Stack>
              </Stack>
              <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: `repeat(${Math.min(byCurrency.length, 2)}, minmax(0, 1fr))` } }}>
                {[...new Set(monthlyGroups.map((row) => row.currency))].map((currency) => <MonthlyChart key={currency} data={monthlyGroups} currency={currency} />)}
              </Box>
            </Paper>
          )}

          <Paper sx={{ p: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>Where your money goes</Typography>
              <Chip size="small" label="By category" variant="outlined" />
            </Stack>
            <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: `repeat(${Math.min(byCurrency.length, 2)}, minmax(0, 1fr))` } }}>
              {byCurrency.map(({ currency }) => (
                <Box key={currency}>
                  <CategoryChart categories={categoryGroups} currency={currency} />
                </Box>
              ))}
            </Box>
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
              <Box sx={{ flexGrow: 1 }}>
                <Typography variant="subtitle1">Compare statements</Typography>
                <Typography variant="body2" color="text.secondary">Find matching transfers, possible duplicates, and missing transactions.</Typography>
              </Box>
              <Button variant="contained" color="secondary" disabled={items.length < 2} onClick={() => onNavigate("reconcile")}>
                Open reconciliation
              </Button>
            </Stack>
            {items.length < 2 && <Typography variant="caption" color="text.secondary">Save at least two statements to compare them.</Typography>}
          </Paper>

          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "1fr 1fr" } }}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="subtitle1" gutterBottom>Anomalies</Typography>
              {anomalyRows.length === 0 ? (
                <Typography variant="body2" color="text.secondary">No rule-based anomaly indicators in the saved statement analyses.</Typography>
              ) : (
                <Stack spacing={1}>
                  {anomalyRows.slice(0, 12).map((anomaly) => (
                    <Alert key={anomaly.key} severity={anomaly.severity === "high" ? "error" : "warning"}>
                      {anomaly.message} <Typography component="span" variant="caption">· {anomaly.fileName}</Typography>
                    </Alert>
                  ))}
                </Stack>
              )}
            </Paper>
            <Paper sx={{ p: 2 }}>
              <Typography variant="subtitle1" gutterBottom>Recurring payments</Typography>
              {recurringRows.length === 0 ? (
                <Typography variant="body2" color="text.secondary">No repeated payment patterns were detected yet.</Typography>
              ) : (
                <TableContainer sx={{ maxWidth: "100%", overflowX: "auto" }}>
                  <Table size="small" sx={{ minWidth: 420 }}>
                    <TableHead><TableRow><TableCell>Payment description</TableCell><TableCell>Amount</TableCell><TableCell>Months</TableCell></TableRow></TableHead>
                    <TableBody>{recurringRows.slice(0, 12).map((payment) => (
                      <TableRow key={payment.key}>
                        <TableCell>{payment.merchant}<Typography display="block" variant="caption" color="text.secondary">{payment.fileName}</Typography></TableCell>
                        <TableCell>{money(payment.amount, payment.currency)}</TableCell>
                        <TableCell>{payment.months.join(", ")}</TableCell>
                      </TableRow>
                    ))}</TableBody>
                  </Table>
                </TableContainer>
              )}
            </Paper>
          </Box>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle1" gutterBottom>Saved statements</Typography>
            <TableContainer sx={{ maxWidth: "100%", overflowX: "auto" }}>
              <Table size="small" sx={{ minWidth: 650 }}>
                <TableHead><TableRow><TableCell>Statement</TableCell><TableCell>Transactions</TableCell><TableCell>Currency</TableCell><TableCell>Extraction quality</TableCell><TableCell>Status</TableCell><TableCell align="right">Export</TableCell></TableRow></TableHead>
                <TableBody>{items.map(({ statement, analytics, currency, analyticsError, reviewMetadata }) => (
                  <TableRow key={statement.id}>
                    <TableCell sx={{ overflowWrap: "anywhere" }}>#{statement.id} · {statement.file_name}</TableCell>
                    <TableCell>{statement.transaction_count}</TableCell>
                    <TableCell><Chip size="small" label={currency} /></TableCell>
                    <TableCell>{reviewMetadata
                      ? `${Math.round(reviewMetadata.average_confidence * 100)}% · ${reviewMetadata.extraction_method}`
                      : "Not recorded"}</TableCell>
                    <TableCell>{analyticsError ? "Analytics unavailable" : `${analytics?.anomalies?.length || 0} anomalies`}</TableCell>
                    <TableCell align="right">
                      <IconButton aria-label={`Export statement ${statement.id} CSV`} component="a" href={onExport(statement.id)} download size="small">
                        <DownloadIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </>
      )}

      <Paper sx={{ p: 2 }}>
        <Typography variant="subtitle1" gutterBottom>Saved merchant corrections</Typography>
        {rulesError && <Alert severity="error" sx={{ mb: 1 }}>{rulesError}</Alert>}
        {rules.length === 0 ? (
          <Typography variant="body2" color="text.secondary">No saved merchant corrections. Correct a merchant in Statement Review to add a reusable rule.</Typography>
        ) : (
          <Stack spacing={0.5}>
            {rules.map((rule) => (
              <Stack key={rule.id} direction="row" alignItems="center" spacing={1}>
                <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>{rule.merchant_name} · {rule.category}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>{rule.aliases.join(", ")}</Typography>
                </Box>
                <IconButton aria-label={`Remove merchant rule ${rule.id}`} size="small" disabled={busyRule === rule.id} onClick={() => removeRule(rule.id)}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
            ))}
          </Stack>
        )}
        <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1 }}>
          OCR confidence is shown per field in Statement Review and saved with new statements; scores are heuristic review signals, not probabilities.
          {" "}<Link component="button" onClick={() => onNavigate("review")}>Open review</Link>
        </Typography>
      </Paper>
    </Stack>
  );
}
