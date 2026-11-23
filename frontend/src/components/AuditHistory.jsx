import { useEffect, useState } from "react";
import { Alert, Chip, Paper, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { api } from "../api/client";

const LABEL = { saved: "Saved", edited: "Edited", deleted: "Deleted", warning: "Warning" };
const COLOR = { saved: "success", edited: "info", deleted: "error", warning: "warning" };

// Plain-language line for one audit entry.
export function describe(e) {
  if (e.action === "edited") return `${e.where} · ${e.field}: ${e.old ?? "(empty)"} → ${e.new ?? "(empty)"}`;
  return e.detail || "";
}

export default function AuditHistory() {
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.auditLog().then(setEntries).catch((e) => setError(e.message));
  }, []);

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="h6">History</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        A record of what was saved, what you edited before saving, and what was deleted. Newest first.
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {entries && entries.length === 0 && <Alert severity="info">Nothing recorded yet. Save a statement to start the history.</Alert>}
      {entries && entries.length > 0 && (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>When</TableCell>
              <TableCell>What</TableCell>
              <TableCell>Statement</TableCell>
              <TableCell>Details</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {entries.map((e) => (
              <TableRow key={e.id}>
                <TableCell>{new Date(e.at).toLocaleString()}</TableCell>
                <TableCell><Chip size="small" color={COLOR[e.action] || "default"} label={LABEL[e.action] || e.action} /></TableCell>
                <TableCell>{e.statement_id ? `#${e.statement_id}` : ""}</TableCell>
                <TableCell>{describe(e)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Paper>
  );
}
