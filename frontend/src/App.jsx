import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  Container,
  Paper,
  Snackbar,
  Stack,
  Tab,
  Tabs,
  TextField,
  Toolbar,
  Typography,
} from "@mui/material";
import { api } from "./api/client";
import UploadPanel from "./components/UploadPanel";
import SummaryBar from "./components/SummaryBar";
import HeaderFieldsCard from "./components/HeaderFieldsCard";
import TransactionsTable from "./components/TransactionsTable";
import SavedStatements from "./components/SavedStatements";
import SaveWarningsDialog from "./components/SaveWarningsDialog";
import AuditHistory from "./components/AuditHistory";
import Analysis from "./components/Analysis";
import { Logo, Watermark } from "./components/Brand";
import FinancialSummary from "./components/FinancialSummary";
import Reconciliation from "./components/Reconciliation";
import Dashboard from "./components/Dashboard";
import TransactionFilters from "./components/TransactionFilters";
import {
  EMPTY_FILTERS,
  buildSavePayload,
  checkBalances,
  detectCategory,
  emptyRow,
  filterRows,
  hasFilters,
  openReviewItems,
  summarize,
  toReviewState,
  validationErrors,
} from "./utils/review";

// `title` and `embedded` are for use as a module inside another app (see StatementAnalyser in module.jsx).
export default function App({ title = "Statement Analyser", embedded = false }) {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [state, setState] = useState(null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [toast, setToast] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [merchants, setMerchants] = useState({}); // row id -> merchant identification (derived, never saved in the statement)
  const [merchantTick, setMerchantTick] = useState(0);
  const [tab, setTab] = useState("review"); // "review", "dashboard", "analysis", "reconcile" or "history"
  const [warnings, setWarnings] = useState(null); // duplicate/overlap warnings waiting for a decision

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const extract = async (file) => {
    setLoading(true);
    setError(null);
    setSaveError(null);
    try {
      const res = await api.extract(file);
      setResult(res);
      setState(toReviewState(res));
      setFilters(EMPTY_FILTERS);
      setNote("");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // State updaters
  const setHeader = (key, value) =>
    setState((s) => ({
      ...s,
      header: { ...s.header, [key]: { ...s.header[key], value } },
      headerAck: { ...s.headerAck, [key]: true },
    }));
  const ackHeader = (key, v) => setState((s) => ({ ...s, headerAck: { ...s.headerAck, [key]: v } }));
  const setCell = (id, key, value) =>
    setState((s) => ({
      ...s,
      rows: s.rows.map((r) => {
        if (r.id !== id) return r;
        const next = { ...r, [key]: { ...r[key], value }, acknowledged: true };
        // A row you added follows its description until you pick a category yourself.
        // Rows from the statement keep the category they already have.
        if (key === "description" && r.added && !r.categoryManual) next.category = detectCategory(value);
        return next;
      }),
    }));
  const setCategory = (id, category) =>
    setState((s) => ({ ...s, rows: s.rows.map((r) => (r.id === id ? { ...r, category, categoryManual: true } : r)) }));
  const ackRow = (id, v) => setState((s) => ({ ...s, rows: s.rows.map((r) => (r.id === id ? { ...r, acknowledged: v } : r)) }));
  const deleteRow = (id) => setState((s) => ({ ...s, rows: s.rows.filter((r) => r.id !== id) }));
  const addRow = () => {
    setFilters(EMPTY_FILTERS); // so the new (empty) row is not hidden by a filter
    setState((s) => ({ ...s, rows: [...s.rows, emptyRow()] }));
  };

  // Ask the backend who the merchant is whenever a description changes (short delay while typing).
  const descKey = state ? state.rows.map((r) => `${r.id}\u0001${r.description.value}`).join("\u0002") : "";
  useEffect(() => {
    if (!state || state.rows.length === 0) {
      setMerchants({});
      return undefined;
    }
    let cancelled = false;
    const ids = state.rows.map((r) => r.id);
    const timer = setTimeout(() => {
      api
        .identifyMerchants(state.rows.map((r) => r.description.value))
        .then((res) => !cancelled && setMerchants(Object.fromEntries(ids.map((id, i) => [id, res[i]]))))
        .catch(() => !cancelled && setMerchants({}));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [descKey, merchantTick]);

  const saveMerchant = async (payload) => {
    await api.saveMerchantMapping(payload);
    setMerchantTick((t) => t + 1);
    setToast("Merchant correction saved for future uploads");
  };

  const shown = useMemo(() => (state ? filterRows(state.rows, filters) : []), [state, filters]);
  const totals = useMemo(() => summarize(shown), [shown]);
  const live = useMemo(() => (state ? checkBalances(state) : null), [state]);
  const open = useMemo(() => (state ? openReviewItems(state) : []), [state]);
  const errors = useMemo(() => (state ? validationErrors(state) : []), [state]);
  const canSave = state && open.length === 0 && errors.length === 0 && !saving;

  // Ask the server about duplicates first. A failed check never blocks saving.
  const trySave = async () => {
    setSaveError(null);
    let found = [];
    try {
      found = await api.checkStatement(buildSavePayload(state, note));
    } catch {
      found = [];
    }
    if (found.length > 0) setWarnings(found);
    else save();
  };

  const save = async () => {
    setWarnings(null);
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await api.save(buildSavePayload(state, note));
      setToast(`Saved statement #${saved.id}`);
      setRefreshKey((k) => k + 1);
      setResult(null);
      setState(null);
    } catch (e) {
      setSaveError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ minHeight: embedded ? "auto" : "100vh", bgcolor: "background.default", position: "relative", overflow: embedded ? "hidden" : "visible" }}>
      <Watermark contained={embedded} />
      <AppBar position={embedded ? "static" : "sticky"} elevation={0} sx={{ bgcolor: "#fff", color: "text.primary", borderBottom: "1px solid", borderColor: "divider", zIndex: 2 }}>
        <Toolbar sx={{ gap: 2, flexWrap: "wrap", py: 1 }}>
          <Logo height={30} />
          <Box sx={{ width: "1px", alignSelf: "stretch", my: 0.5, bgcolor: "divider" }} />
          <Box sx={{ flexGrow: 1 }}>
            <Typography variant="h6" sx={{ lineHeight: 1.15 }}>{title}</Typography>
            <Typography variant="caption" color="text.secondary">Read, check and analyse bank statements</Typography>
          </Box>
          {health && (
            <Stack direction="row" spacing={1}>
              <Chip size="small" label={health.tesseract_available ? "OCR ready" : "OCR unavailable"} color={health.tesseract_available ? "success" : "warning"} />
              <Chip
                size="small"
                label={health.ollama_enabled ? (health.ollama_reachable ? "Local LLM on" : "Local LLM offline") : "Local LLM off"}
                variant="outlined"
              />
            </Stack>
          )}
        </Toolbar>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} textColor="secondary" indicatorColor="secondary" variant="scrollable" scrollButtons="auto" sx={{ px: 2 }}>
          <Tab value="review" label="Statement review" />
          <Tab value="dashboard" label="Dashboard" />
          <Tab value="analysis" label="Analysis" />
          <Tab value="reconcile" label="Reconciliation" />
          <Tab value="history" label="History" />
        </Tabs>
      </AppBar>
      <Container maxWidth="xl" sx={{ py: 3, position: "relative", zIndex: 1 }}>
        <Alert severity="info" sx={{ mb: 2 }}>
          This tool assists review. Use dummy statements only, and verify every flagged value against the document before saving.
        </Alert>
        {tab === "analysis" && <Analysis />}
        {tab === "dashboard" && <Dashboard onNavigate={setTab} />}
        {tab === "reconcile" && <Reconciliation />}
        {tab === "history" && <AuditHistory />}
        <Stack spacing={2} sx={{ display: tab === "review" ? "flex" : "none" }}>
          <UploadPanel onExtract={extract} loading={loading} error={error} />
          {state && result && (
            <>
              <SummaryBar result={result} live={live} openCount={open.length} />
              <FinancialSummary totals={totals} filtered={hasFilters(filters)} shown={shown.length} total={state.rows.length} />
              <HeaderFieldsCard header={state.header} headerAck={state.headerAck} onChange={setHeader} onAck={ackHeader} />
              <TransactionFilters filters={filters} onChange={setFilters} shown={shown.length} total={state.rows.length} />
              <TransactionsTable
                rows={state.rows}
                shownRows={shown}
                mismatched={live.mismatched}
                onChange={setCell}
                onCategory={setCategory}
                onAck={ackRow}
                onDelete={deleteRow}
                onAdd={addRow}
                merchants={merchants}
                onMerchantSave={saveMerchant}
              />
              <Paper sx={{ p: 2 }}>
                <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
                  <TextField
                    size="small"
                    label="Reviewer note (optional)"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    sx={{ flexGrow: 1 }}
                    inputProps={{ maxLength: 1000 }}
                  />
                  <Button variant="outlined" onClick={() => { setResult(null); setState(null); }}>
                    Discard
                  </Button>
                  <Button variant="contained" color="secondary" disabled={!canSave} onClick={trySave}>
                    {saving ? "Saving…" : "Save reviewed data"}
                  </Button>
                </Stack>
                {open.length > 0 && (
                  <Typography variant="body2" color="warning.main" sx={{ mt: 1 }} data-testid="open-items">
                    Review required before saving: {open.slice(0, 8).map((o) => o.label).join(", ")}
                    {open.length > 8 ? ` and ${open.length - 8} more` : ""}
                  </Typography>
                )}
                {errors.length > 0 && (
                  <Alert severity="error" sx={{ mt: 1 }}>
                    {errors.slice(0, 5).join(" · ")}
                  </Alert>
                )}
                {saveError && <Alert severity="error" sx={{ mt: 1 }}>{saveError}</Alert>}
              </Paper>
            </>
          )}
          <SavedStatements refreshKey={refreshKey} />
        </Stack>
      </Container>
      <SaveWarningsDialog warnings={warnings} onSaveAnyway={save} onCancel={() => setWarnings(null)} />
      <Snackbar open={Boolean(toast)} autoHideDuration={4000} onClose={() => setToast(null)} message={toast} />
    </Box>
  );
}
