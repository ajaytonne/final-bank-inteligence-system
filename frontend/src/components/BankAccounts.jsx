import { useCallback, useEffect, useState } from "react";
import { Alert, Box, Button, Checkbox, FormControlLabel, Paper, Stack, Switch, TextField, Typography } from "@mui/material";
import { api } from "../api/client";

const empty = { bank_name: "", account_label: "", account_number_masked: "", ownership_confirmed: false };

/** Step 1: tell the app which bank account each saved statement belongs to, and which accounts are yours. */
export default function BankAccounts() {
  const [accounts, setAccounts] = useState([]);
  const [statements, setStatements] = useState([]);
  const [assigned, setAssigned] = useState({}); // statement id -> account id
  const [form, setForm] = useState(empty);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    Promise.all([api.listAccounts(), api.list(), api.listAssignments()])
      .then(([acc, st, asg]) => {
        setAccounts(acc);
        setStatements(st);
        setAssigned(Object.fromEntries(asg.map((a) => [a.statement_id, a.account_id])));
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const run = async (fn) => {
    setError(null);
    try {
      await fn();
      load();
    } catch (e) {
      setError(e.message);
    }
  };
  const add = () =>
    run(async () => {
      await api.createAccount({ ...form, account_number_masked: form.account_number_masked.trim() || null });
      setForm(empty);
    });
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle2">1. Bank accounts</Typography>
      <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1.5 }}>
        Add each account, say which ones are yours, then link every saved statement to its account. Linking is optional, but a transfer is only
        treated as "between my own accounts" when both accounts are marked as yours.
      </Typography>
      {error && <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>{error}</Alert>}
      <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", md: "repeat(4, 1fr) auto" }, alignItems: "center" }}>
        <TextField size="small" label="Bank name" value={form.bank_name} onChange={set("bank_name")} inputProps={{ "aria-label": "Bank name" }} InputLabelProps={{ shrink: true }} />
        <TextField size="small" label="Account name" value={form.account_label} onChange={set("account_label")} inputProps={{ "aria-label": "Account name" }} InputLabelProps={{ shrink: true }} placeholder="e.g. SBI Savings" />
        <TextField size="small" label="Account number (last 4 digits)" value={form.account_number_masked} onChange={set("account_number_masked")} inputProps={{ "aria-label": "Account number (last 4 digits)", maxLength: 40 }} InputLabelProps={{ shrink: true }} />
        <FormControlLabel
          control={<Checkbox size="small" checked={form.ownership_confirmed} onChange={(e) => setForm({ ...form, ownership_confirmed: e.target.checked })} />}
          label={<Typography variant="body2">This is my own account</Typography>}
        />
        <Button variant="contained" disabled={!form.bank_name.trim() || !form.account_label.trim()} onClick={add}>
          Add account
        </Button>
      </Box>

      {accounts.length > 0 && (
        <Stack spacing={0.5} sx={{ mt: 2 }}>
          {accounts.map((a) => (
            <Stack key={a.id} direction="row" alignItems="center" spacing={1}>
              <Typography variant="body2" sx={{ flexGrow: 1 }}>
                <strong>{a.account_label}</strong> · {a.bank_name} {a.account_number_masked || ""}
              </Typography>
              <FormControlLabel
                control={<Switch size="small" checked={a.ownership_confirmed} onChange={(e) => run(() => api.updateAccount(a.id, { ownership_confirmed: e.target.checked }))} inputProps={{ "aria-label": `Mine: ${a.account_label}` }} />}
                label={<Typography variant="caption">Mine</Typography>}
              />
            </Stack>
          ))}
        </Stack>
      )}

      {statements.length > 0 && accounts.length > 0 && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>Link saved statements to accounts</Typography>
          <Stack spacing={1}>
            {statements.map((s) => (
              <Stack key={s.id} direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                <Typography variant="body2" sx={{ flexGrow: 1 }}>
                  #{s.id} {s.file_name} <Typography component="span" variant="caption" color="text.secondary">({s.transaction_count} transactions)</Typography>
                </Typography>
                <TextField
                  select
                  size="small"
                  value={assigned[s.id] ?? ""}
                  onChange={(e) => run(() => api.assignStatement(s.id, e.target.value === "" ? null : Number(e.target.value)))}
                  SelectProps={{ native: true }}
                  inputProps={{ "aria-label": `Account for statement ${s.id}` }}
                  sx={{ minWidth: 220 }}
                >
                  <option value="">Not linked</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.account_label}
                    </option>
                  ))}
                </TextField>
              </Stack>
            ))}
          </Stack>
        </Box>
      )}
    </Paper>
  );
}
