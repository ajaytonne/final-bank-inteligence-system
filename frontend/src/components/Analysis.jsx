import { useEffect, useRef, useState } from "react";
import { Alert, Button, CircularProgress, Paper, Stack, TextField, Typography } from "@mui/material";
import { api } from "../api/client";
import { validateClientFile } from "../utils/review";
import AnalysisResult from "./AnalysisResult";

// The "Analysis" tab: upload a statement (full analysis with file checks) or analyse one you already saved.
export default function Analysis() {
  const [file, setFile] = useState(null);
  const [password, setPassword] = useState("");
  const [saved, setSaved] = useState([]);
  const [savedId, setSavedId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const input = useRef(null);

  useEffect(() => {
    api.list().then(setSaved).catch(() => setSaved([]));
  }, []);

  const run = async (call) => {
    setBusy(true);
    setError(null);
    setData(null);
    try {
      setData(await call());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const pick = (e) => {
    const f = e.target.files?.[0] || null;
    const problem = f ? validateClientFile(f) : null;
    setFile(problem ? null : f);
    setError(problem);
  };

  return (
    <Stack spacing={2}>
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6">Analyse a statement</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Get balances, salary, EMIs, bounced items, cash deposits and possible tampering in one view. Use dummy statements only.
        </Typography>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
          <Button variant="outlined" onClick={() => input.current?.click()}>{file ? file.name : "Choose a statement file"}</Button>
          <input ref={input} type="file" hidden data-testid="analysis-file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp" onChange={pick} />
          <TextField size="small" type="password" label="PDF password (only if locked)" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" />
          <Button variant="contained" disabled={!file || busy} onClick={() => run(() => api.analyse(file, password))}>
            {busy ? <CircularProgress size={20} /> : "Analyse file"}
          </Button>
        </Stack>
        {saved.length > 0 && (
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }} sx={{ mt: 2 }}>
            <TextField select size="small" label="Or a saved statement" value={savedId} onChange={(e) => setSavedId(e.target.value)} SelectProps={{ native: true }} InputLabelProps={{ shrink: true }} sx={{ minWidth: 280 }} inputProps={{ "aria-label": "Saved statement" }}>
              <option value="">Choose…</option>
              {saved.map((s) => <option key={s.id} value={s.id}>{`#${s.id} ${s.file_name}`}</option>)}
            </TextField>
            <Button variant="outlined" disabled={!savedId || busy} onClick={() => run(() => api.savedAnalytics(savedId))}>Analyse saved statement</Button>
          </Stack>
        )}
        {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
      </Paper>
      {data && <Paper sx={{ p: 2 }}><AnalysisResult data={data} /></Paper>}
    </Stack>
  );
}
