import { useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
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
import { CATEGORIES, fieldError, rowType, txnFieldType } from "../utils/review";

const COLS = [
  { key: "date", label: "Date", width: 130 },
  { key: "effective_date", label: "Effective date", width: 130 },
  { key: "description", label: "Description", width: 220 },
  { key: "category", label: "Category", width: 120 }, // dropdown, see CategoryCell
  { key: "type", label: "Type", width: 80 }, // Income / Expense, see TypeCell
  { key: "reference", label: "Cheque / reference", width: 130 },
  { key: "withdrawal", label: "Withdrawal", width: 110, align: "right" },
  { key: "deposit", label: "Deposit", width: 110, align: "right" },
  { key: "balance", label: "Balance", width: 120, align: "right" },
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

function CategoryCell({ row, label, onCategory }) {
  return (
    <TableCell sx={{ minWidth: 120 }}>
      <TextField
        select
        variant="standard"
        size="small"
        fullWidth
        value={row.category}
        onChange={(e) => onCategory(row.id, e.target.value)}
        SelectProps={{ native: true }}
        inputProps={{ "aria-label": `Category row ${label}`, style: { fontSize: 13 } }}
      >
        {CATEGORIES.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </TextField>
    </TableCell>
  );
}

function TypeCell({ row }) {
  const type = rowType(row);
  return (
    <TableCell>
      {type ? (
        <Chip size="small" variant="outlined" label={type} color={type === "Income" ? "success" : "error"} />
      ) : (
        <Typography variant="caption" color="text.secondary">
          —
        </Typography>
      )}
    </TableCell>
  );
}

// `shownRows` is `rows` after the Search & Filter box has been applied (App does the filtering).
export default function TransactionsTable({ rows, shownRows = rows, mismatched, onChange, onCategory, onAck, onDelete, onAdd }) {
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const visible = flaggedOnly ? shownRows.filter((r) => r.needsReview || mismatched.has(r.id)) : shownRows;
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
      <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1 }}>
        Category is picked automatically from the description. You can change it any time.
      </Typography>
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
                  {COLS.map((c) =>
                    c.key === "category" ? (
                      <CategoryCell key={c.key} row={r} label={idx + 1} onCategory={onCategory} />
                    ) : c.key === "type" ? (
                      <TypeCell key={c.key} row={r} />
                    ) : (
                      <Cell key={c.key} row={r} col={c} onChange={onChange} />
                    )
                  )}
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
                    {rows.length === 0
                      ? "No transactions were extracted. Add rows manually if needed."
                      : shownRows.length === 0
                        ? "No transactions found. Try changing or clearing the filters."
                        : "No flagged rows."}
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
