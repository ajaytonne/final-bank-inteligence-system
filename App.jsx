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
import {
  buildSavePayload,
  checkBalances,
  emptyRow,
  openReviewItems,
  toReviewState,
  validationErrors,
} from "./utils/review";

export default function App() {
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
      rows: s.rows.map((r) => (r.id === id ? { ...r, [key]: { ...r[key], value }, acknowledged: true } : r)),
    }));
  const ackRow = (id, v) => setState((s) => ({ ...s, rows: s.rows.map((r) => (r.id === id ? { ...r, acknowledged: v } : r)) }));
  const deleteRow = (id) => setState((s) => ({ ...s, rows: s.rows.filter((r) => r.id !== id) }));
  const addRow = () => setState((s) => ({ ...s, rows: [...s.rows, emptyRow()] }));

  const live = useMemo(() => (state ? checkBalances(state) : null), [state]);
  const open = useMemo(() => (state ? openReviewItems(state) : []), [state]);
  const errors = useMemo(() => (state ? validationErrors(state) : []), [state]);
  const canSave = state && open.length === 0 && errors.length === 0 && !saving;

  const save = async () => {
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
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="static" color="primary" elevation={0}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 700 }}>
            Bank Statement Intelligence
          </Typography>
          {health && (
            <Stack direction="row" spacing={1}>
              <Chip size="small" label={health.tesseract_available ? "OCR ready" : "OCR unavailable"} color={health.tesseract_available ? "success" : "warning"} />
              <Chip
                size="small"
                label={health.ollama_enabled ? (health.ollama_reachable ? "Local LLM on" : "Local LLM offline") : "Local LLM off"}
                sx={{ color: "white", borderColor: "rgba(255,255,255,.5)" }}
                variant="outlined"
              />
            </Stack>
          )}
        </Toolbar>
      </AppBar>
      <Container maxWidth="xl" sx={{ py: 3 }}>
        <Alert severity="info" sx={{ mb: 2 }}>
          This tool assists review. Use dummy statements only, and verify every flagged value against the document before saving.
        </Alert>
        <Stack spacing={2}>
          <UploadPanel onExtract={extract} loading={loading} error={error} />
          {state && result && (
            <>
              <SummaryBar result={result} live={live} openCount={open.length} />
              <HeaderFieldsCard header={state.header} headerAck={state.headerAck} onChange={setHeader} onAck={ackHeader} />
              <TransactionsTable rows={state.rows} mismatched={live.mismatched} onChange={setCell} onAck={ackRow} onDelete={deleteRow} onAdd={addRow} />
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
                  <Button variant="contained" color="secondary" disabled={!canSave} onClick={save}>
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
      <Snackbar open={Boolean(toast)} autoHideDuration={4000} onClose={() => setToast(null)} message={toast} />
    </Box>
  );
}
