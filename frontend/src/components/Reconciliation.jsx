import { useCallback, useEffect, useState } from "react";
import {
  Alert, Box, Button, Chip, IconButton, Paper, Stack, Tab, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Tabs, TextField, Tooltip, Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DownloadIcon from "@mui/icons-material/Download";
import { api } from "../api/client";
import { formatRupees } from "../utils/review";
import BankAccounts from "./BankAccounts";

const WINDOWS = [0, 1, 2, 3, 5, 7];
const GROUPS = [
  { key: "review", label: "Needs review", statuses: ["Possible Match", "Manual Review"] },
  { key: "matched", label: "Matched", statuses: ["Matched"] },
  { key: "timing", label: "Timing differences", statuses: ["Timing Difference"] },
  { key: "unmatched", label: "Unmatched", statuses: ["Unmatched", "Missing Transaction"] },
  { key: "duplicates", label: "Duplicates", statuses: ["Duplicate Candidate"] },
  { key: "rejected", label: "Rejected", statuses: ["Rejected Match"] },
];
const COLOR = {
  Matched: "success", "Timing Difference": "info", "Possible Match": "warning", "Manual Review": "warning",
  "Duplicate Candidate": "warning", "Missing Transaction": "error", Unmatched: "default", "Rejected Match": "default",
};
const rupees = (v) => formatRupees(Number(v));

function Txn({ t, index }) {
  if (!t) return <Typography variant="caption" color="text.secondary">—</Typography>;
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">Row {index + 1} · {t.date || "no date"}</Typography>
      <Typography variant="body2">{t.description || "(no description)"}</Typography>
      <Typography variant="caption" color="text.secondary">
        {t.reference ? `Ref ${t.reference} · ` : ""}
        <strong>{rupees(t.amount)} {t.direction === "debit" ? "Dr" : "Cr"}</strong>
      </Typography>
    </Box>
  );
}

function Summary({ summary: s }) {
  const items = [
    ["Statement A transactions", s.total_a], ["Statement B transactions", s.total_b], ["Matched", s.matched],
    ["Possible matches", s.possible_matches], ["Manual review", s.manual_review], ["Unmatched", s.unmatched],
    ["Duplicate candidates", s.duplicate_candidates], ["Timing differences", s.timing_differences],
    ["Confirmed internal transfers", s.confirmed_internal_transfers],
    ["Total matched amount", rupees(s.total_matched_amount)], ["Total unmatched amount", rupees(s.total_unmatched_amount)],
    ...(s.period_gaps ? [["Outside other statement's dates", s.period_gaps]] : []),
  ];
  return (
    <Box sx={{ display: "grid", gap: 1, gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))" }}>
      {items.map(([label, value]) => (
        <Paper key={label} sx={{ p: 1.5 }}>
          <Typography variant="caption" color="text.secondary">{label}</Typography>
          <Typography variant="h6" data-testid={`sum-${label}`}>{value}</Typography>
        </Paper>
      ))}
    </Box>
  );
}

/** Reconciliation page: choose two saved statements, compare them, review the results. */
export default function Reconciliation() {
  const [statements, setStatements] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [kind, setKind] = useState("inter_bank");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [windowDays, setWindowDays] = useState(2);
  const [starting, setStarting] = useState(false);
  const [detail, setDetail] = useState(null);
  const [totals, setTotals] = useState(null);
  const [group, setGroup] = useState("review");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    api.list().then(setStatements).catch((e) => setError(e.message));
    api.listRecon().then(setSessions).catch(() => setSessions([]));
  }, []);
  useEffect(refresh, [refresh]);

  const show = (d) => {
    setDetail(d);
    const s = d.summary;
    setGroup((g) => (d.matches.some((m) => GROUPS.find((x) => x.key === g)?.statuses.includes(m.status)) ? g : s.possible_matches + s.manual_review > 0 ? "review" : "matched"));
  };
  useEffect(() => {
    if (!detail) return;
    api.consolidated(detail.session.id).then(setTotals).catch(() => setTotals(null));
  }, [detail]);

  const changeKind = (value) => {
    setKind(value);
    setWindowDays(value === "internal" ? 0 : 2);
  };
  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const session = await api.createRecon({ kind, statement_a_id: Number(a), statement_b_id: Number(b), date_window_days: Number(windowDays) });
      show(await api.runRecon(session.id));
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setStarting(false);
    }
  };
  const open = async (id) => {
    setError(null);
    try {
      const d = await api.getRecon(id);
      setGroup("review");
      show(d);
    } catch (e) {
      setError(e.message);
    }
  };
  const remove = async (id) => {
    if (!window.confirm("Delete this reconciliation result? Your statements are not affected.")) return;
    try {
      await api.removeRecon(id);
      if (detail?.session.id === id) setDetail(null);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  };
  const decide = async (m, action) => {
    setBusy(m.id);
    setError(null);
    try {
      show(await (action === "confirm" ? api.confirmMatch : api.rejectMatch)(detail.session.id, m.id));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const label = (s) => `#${s.id} ${s.file_name}`;
  const rows = detail ? detail.matches.filter((m) => GROUPS.find((g) => g.key === group).statuses.includes(m.status)) : [];
  const count = (g) => (detail ? detail.matches.filter((m) => g.statuses.includes(m.status)).length : 0);

  return (
    <Stack spacing={2}>
      <BankAccounts />

      <Paper sx={{ p: 2 }}>
        <Typography variant="subtitle2">2. Choose what to compare</Typography>
        <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
          Internal: two statements of the same account (finds repeats and gaps). Inter-bank: statements of two accounts (finds transfers between them).
          Results are suggestions: nothing is changed or deleted, and only you confirm uncertain matches.
        </Typography>
        {statements.length < 2 && <Alert severity="info" sx={{ mb: 1 }}>Save at least two reviewed statements first (Statement review tab).</Alert>}
        <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", md: "repeat(4, 1fr) auto" }, alignItems: "center" }}>
          <TextField select size="small" label="Reconciliation type" value={kind} onChange={(e) => changeKind(e.target.value)} SelectProps={{ native: true }} inputProps={{ "aria-label": "Reconciliation type" }} InputLabelProps={{ shrink: true }}>
            <option value="inter_bank">Inter-bank (transfers between accounts)</option>
            <option value="internal">Internal (same account)</option>
          </TextField>
          <TextField select size="small" label="Statement A" value={a} onChange={(e) => setA(e.target.value)} SelectProps={{ native: true }} inputProps={{ "aria-label": "Statement A" }} InputLabelProps={{ shrink: true }}>
            <option value="">Choose…</option>
            {statements.map((s) => <option key={s.id} value={s.id}>{label(s)}</option>)}
          </TextField>
          <TextField select size="small" label="Statement B" value={b} onChange={(e) => setB(e.target.value)} SelectProps={{ native: true }} inputProps={{ "aria-label": "Statement B" }} InputLabelProps={{ shrink: true }}>
            <option value="">Choose…</option>
            {statements.map((s) => <option key={s.id} value={s.id}>{label(s)}</option>)}
          </TextField>
          <TextField select size="small" label="Allowed date difference" value={windowDays} onChange={(e) => setWindowDays(e.target.value)} SelectProps={{ native: true }} inputProps={{ "aria-label": "Allowed date difference" }} InputLabelProps={{ shrink: true }}>
            {WINDOWS.map((w) => <option key={w} value={w}>{w === 0 ? "Same day only" : `${w} day${w > 1 ? "s" : ""}`}</option>)}
          </TextField>
          <Button variant="contained" color="secondary" disabled={!a || !b || starting} onClick={start}>
            {starting ? "Comparing…" : "Start reconciliation"}
          </Button>
        </Box>
        {error && <Alert severity="error" sx={{ mt: 1.5 }} onClose={() => setError(null)}>{error}</Alert>}
        {sessions.length > 0 && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>Earlier reconciliations</Typography>
            {sessions.slice(0, 5).map((s) => (
              <Stack key={s.id} direction="row" alignItems="center" spacing={1}>
                <Button size="small" onClick={() => open(s.id)} aria-label={`Open reconciliation ${s.id}`}>
                  #{s.id} · {s.kind === "internal" ? "Internal" : "Inter-bank"} · {s.a_label} vs {s.b_label}
                </Button>
                <Typography variant="caption" color="text.secondary">{new Date(s.created_at).toLocaleString()}</Typography>
                <IconButton size="small" aria-label={`Delete reconciliation ${s.id}`} onClick={() => remove(s.id)}><DeleteOutlineIcon fontSize="small" /></IconButton>
              </Stack>
            ))}
          </Box>
        )}
      </Paper>

      {detail && (
        <>
          <Paper sx={{ p: 2 }}>
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
              <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
                3. Summary · {detail.session.a_label} vs {detail.session.b_label}
              </Typography>
              <Button size="small" startIcon={<DownloadIcon />} component="a" href={api.exportUrl(detail.session.id)}>
                Export CSV
              </Button>
            </Stack>
            {detail.session.notes.map((n) => <Alert key={n} severity="info" sx={{ mb: 1, py: 0 }}>{n}</Alert>)}
            <Summary summary={detail.summary} />
            {totals && (
              <Typography variant="body2" sx={{ mt: 1.5 }} data-testid="consolidated">
                Combined income {rupees(totals.income)} · expenses {rupees(totals.expenses)} · savings{" "}
                <Box component="span" sx={{ color: Number(totals.savings) < 0 ? "error.main" : "success.main", fontWeight: 600 }}>{rupees(totals.savings)}</Box>
                {totals.excluded_transfer_count > 0
                  ? ` (${totals.excluded_transfer_count} confirmed transfer(s) between your own accounts, ${rupees(totals.excluded_amount)}, left out)`
                  : " (no confirmed transfers between your own accounts are left out)"}
              </Typography>
            )}
          </Paper>

          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" gutterBottom>4. Review results</Typography>
            <Tabs value={group} onChange={(_, v) => setGroup(v)} variant="scrollable" scrollButtons="auto" sx={{ mb: 1 }}>
              {GROUPS.map((g) => <Tab key={g.key} value={g.key} label={`${g.label} (${count(g)})`} />)}
            </Tabs>
            <TableContainer sx={{ maxHeight: 560 }}>
              <Table stickyHeader size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Status</TableCell>
                    <TableCell>Statement A</TableCell>
                    <TableCell>Statement B</TableCell>
                    <TableCell>Confidence</TableCell>
                    <TableCell>Why</TableCell>
                    <TableCell>Your decision</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((m) => {
                    const pair = m.a && m.b;
                    return (
                      <TableRow key={m.id} hover data-testid={`recon-row-${m.id}`}>
                        <TableCell>
                          <Chip size="small" label={m.status} color={COLOR[m.status]} variant={m.status === "Matched" ? "filled" : "outlined"} />
                          {m.internal_transfer && (
                            <Chip size="small" sx={{ mt: 0.5 }} color="secondary" variant={m.confirmation_status === "confirmed" ? "filled" : "outlined"}
                              label={m.confirmation_status === "confirmed" ? "Own-account transfer (confirmed)" : "Possible own-account transfer"} />
                          )}
                        </TableCell>
                        <TableCell sx={{ minWidth: 200 }}><Txn t={m.a} index={m.a_index} /></TableCell>
                        <TableCell sx={{ minWidth: 200 }}><Txn t={m.b} index={m.b_index} /></TableCell>
                        <TableCell>{pair ? `${Math.round(m.confidence * 100)}%` : "—"}</TableCell>
                        <TableCell sx={{ minWidth: 260 }}><Typography variant="caption">{m.reason}</Typography></TableCell>
                        <TableCell sx={{ minWidth: 190 }}>
                          {pair ? (
                            <Stack direction="row" spacing={0.5} alignItems="center">
                              {m.confirmation_status !== "confirmed" && (
                                <Button size="small" variant="outlined" color="success" disabled={busy === m.id} onClick={() => decide(m, "confirm")} aria-label={`Confirm match ${m.id}`}>
                                  {m.internal_transfer ? "Confirm transfer" : "Confirm"}
                                </Button>
                              )}
                              {m.status !== "Rejected Match" && (
                                <Button size="small" variant="outlined" color="error" disabled={busy === m.id} onClick={() => decide(m, "reject")} aria-label={`Reject match ${m.id}`}>
                                  Reject
                                </Button>
                              )}
                              {m.confirmation_status === "confirmed" && <Typography variant="caption" color="success.main">Confirmed</Typography>}
                              {m.confirmation_status === "auto" && (
                                <Tooltip title="Strong evidence, so it is marked automatically. You can still confirm or reject it.">
                                  <Typography variant="caption" color="text.secondary">auto</Typography>
                                </Tooltip>
                              )}
                            </Stack>
                          ) : (
                            <Typography variant="caption" color="text.secondary">Nothing to decide</Typography>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {rows.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={6} align="center">
                        <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>Nothing in this list.</Typography>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </>
      )}
    </Stack>
  );
}
