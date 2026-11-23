import { useEffect, useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import { MERCHANT_CATEGORIES } from "../utils/review";

/** Lets the user fix a merchant. The original narration is shown but cannot be edited. */
export default function MerchantCorrectionDialog({ row, current, onClose, onSave }) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("Other");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!row) return;
    const known = current && current.merchant_name !== "Unknown Merchant";
    setName(known ? current.merchant_name : "");
    setCategory(known ? current.category : "Other");
    setError(null);
  }, [row, current]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave({ narration: row.description.value, merchant_name: name.trim(), category });
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={Boolean(row)} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Correct merchant</DialogTitle>
      <DialogContent>
        {row && (
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField size="small" label="Original narration (not changed)" value={row.description.value} disabled InputLabelProps={{ shrink: true }} />
            <TextField size="small" label="Merchant name" value={name} onChange={(e) => setName(e.target.value)} autoFocus inputProps={{ maxLength: 100, "aria-label": "Merchant name" }} InputLabelProps={{ shrink: true }} />
            <TextField
              select
              size="small"
              label="Merchant category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              SelectProps={{ native: true }}
              inputProps={{ "aria-label": "Merchant category" }}
              InputLabelProps={{ shrink: true }}
            >
              {MERCHANT_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </TextField>
            <Typography variant="caption" color="text.secondary">
              Saved for future uploads: similar narrations will use this merchant. Only the displayed merchant changes.
            </Typography>
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" color="secondary" disabled={!name.trim() || saving} onClick={save}>
          {saving ? "Saving…" : "Save correction"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
