import { useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  IconButton,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import AddIcon from "@mui/icons-material/Add";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import ConfidenceChip from "./ConfidenceChip";
import { fieldError, txnFieldType } from "../utils/review";

const COLS = [
  { key: "date", label: "Date", width: 150 },
  { key: "effective_date", label: "Effective date", width: 150 },
  { key: "description", label: "Description", width: 260 },
  { key: "reference", label: "Cheque / reference", width: 160 },
  { key: "withdrawal", label: "Withdrawal", width: 120, align: "right" },
  { key: "deposit", label: "Deposit", width: 120, align: "right" },
  { key: "balance", label: "Balance", width: 130, align: "right" },
];

function Cell({ row, col, onChange }) {
  const f = row[col.key];
  const type = txnFieldType(col.key);
  const err = fieldError(type, f.value);
  const lowConf = f.needsReview && f.value !== "";
  return (
    <TableCell sx={{ minWidth: col.width }}>
      <Tooltip title={err || f.note || ""} disableHoverListener={!err && !f.note}>
        <TextField
          variant="standard"
          size="small"
          fullWidth
          type={type === "date" ? "date" : "text"}
          value={f.value}
          error={Boolean(err)}
          onChange={(e) => onChange(row.id, col.key, e.target.value)}
          inputProps={{
            "aria-label": `${col.label} row ${row.id}`,
            style: { textAlign: col.align || "left", fontSize: 13 },
            inputMode: type === "amount" ? "decimal" : undefined,
          }}
          sx={lowConf ? { "& input": { textDecoration: "underline dotted #b45309" } } : undefined}
        />
      </Tooltip>
    </TableCell>
  );
}

export default function TransactionsTable({ rows, mismatched, onChange, onAck, onDelete, onAdd }) {
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const visible = flaggedOnly ? rows.filter((r) => r.needsReview || mismatched.has(r.id)) : rows;
  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 1 }}>
        <Typography variant="subtitle2">Transactions ({rows.length})</Typography>
        <Box sx={{ flexGrow: 1 }} />
        <FormControlLabel
          control={<Switch size="small" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />}
          label={<Typography variant="body2">Flagged only</Typography>}
        />
        <Button size="small" startIcon={<AddIcon />} onClick={onAdd}>
          Add row
        </Button>
      </Stack>
      <TableContainer sx={{ maxHeight: 560 }}>
        <Table stickyHeader size="small">
          <TableHead>
            <TableRow>
              <TableCell>#</TableCell>
              {COLS.map((c) => (
                <TableCell key={c.key} align={c.align}>
                  {c.label}
                </TableCell>
              ))}
              <TableCell>Score</TableCell>
              <TableCell>Review</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {visible.map((r) => {
              const idx = rows.indexOf(r);
              const mismatch = mismatched.has(r.id);
              const flagged = (r.needsReview && !r.acknowledged) || mismatch;
              const serverIssues = r.issues.filter((i) => !i.startsWith("Running balance mismatch")); // live recheck
              const issues = [...serverIssues, ...(mismatch ? ["Running balance does not match current values"] : [])];
              return (
                <TableRow key={r.id} hover sx={flagged ? { bgcolor: "#fffbeb" } : undefined} data-testid={`txn-row-${idx}`}>
                  <TableCell>
                    <Stack direction="row" alignItems="center" spacing={0.5}>
                      <span>{idx + 1}</span>
                      {issues.length > 0 && (
                        <Tooltip title={issues.join(" · ")}>
                          <WarningAmberIcon fontSize="small" color="warning" data-testid={`row-warning-${idx}`} />
                        </Tooltip>
                      )}
                    </Stack>
                  </TableCell>
                  {COLS.map((c) => (
                    <Cell key={c.key} row={r} col={c} onChange={onChange} />
                  ))}
                  <TableCell>
                    {r.added ? <Typography variant="caption">manual</Typography> : <ConfidenceChip confidence={r.confidence} />}
                  </TableCell>
                  <TableCell>
                    {r.needsReview ? (
                      <Tooltip title="Mark as checked against the document">
                        <Checkbox
                          size="small"
                          checked={r.acknowledged}
                          onChange={(e) => onAck(r.id, e.target.checked)}
                          inputProps={{ "aria-label": `Reviewed row ${idx + 1}` }}
                        />
                      </Tooltip>
                    ) : (
                      <Typography variant="caption" color="text.secondary">
                        ok
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    <IconButton size="small" aria-label={`Delete row ${idx + 1}`} onClick={() => onDelete(r.id)}>
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              );
            })}
            {visible.length === 0 && (
              <TableRow>
                <TableCell colSpan={COLS.length + 4} align="center">
                  <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
                    {rows.length ? "No flagged rows." : "No transactions were extracted. Add rows manually if needed."}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}
