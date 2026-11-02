import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { api } from "../api/client";
import { formatAmount } from "../utils/review";

export default function SavedStatements({ refreshKey }) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);

  const load = useCallback(() => {
    api.list().then(setItems).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load, refreshKey]);

  const view = async (id) => {
    try {
      setOpen(await api.get(id));
    } catch (e) {
      setError(e.message);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this saved statement?")) return;
    try {
      await api.remove(id);
      load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle2">Saved statements</Typography>
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      {items.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Nothing saved yet.
        </Typography>
      ) : (
        <List dense>
          {items.map((s) => (
            <ListItem
              key={s.id}
              disablePadding
              secondaryAction={
                <IconButton edge="end" aria-label={`Delete statement ${s.id}`} onClick={() => remove(s.id)}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              }
            >
              <ListItemButton onClick={() => view(s.id)}>
                <ListItemText
                  primary={`${s.account_holder || "Unknown holder"} — ${s.file_name}`}
                  secondary={`${s.transaction_count} transactions · ${new Date(s.created_at).toLocaleString()}`}
                />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      )}
      <Dialog open={Boolean(open)} onClose={() => setOpen(null)} maxWidth="md" fullWidth>
        {open && (
          <>
            <DialogTitle>
              {open.statement.header.account_holder || "Statement"} · {open.statement.header.account_number_masked || ""}
            </DialogTitle>
            <DialogContent>
              <Typography variant="body2" gutterBottom>
                Period {open.statement.header.period_start || "?"} to {open.statement.header.period_end || "?"} · Opening{" "}
                {formatAmount(open.statement.header.opening_balance)} · Closing {formatAmount(open.statement.header.closing_balance)}
              </Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Date</TableCell>
                    <TableCell>Description</TableCell>
                    <TableCell>Ref</TableCell>
                    <TableCell align="right">Withdrawal</TableCell>
                    <TableCell align="right">Deposit</TableCell>
                    <TableCell align="right">Balance</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {open.statement.transactions.map((t, i) => (
                    <TableRow key={i}>
                      <TableCell>{t.date}</TableCell>
                      <TableCell>{t.description}</TableCell>
                      <TableCell>{t.reference}</TableCell>
                      <TableCell align="right">{formatAmount(t.withdrawal)}</TableCell>
                      <TableCell align="right">{formatAmount(t.deposit)}</TableCell>
                      <TableCell align="right">{formatAmount(t.balance)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </DialogContent>
          </>
        )}
      </Dialog>
    </Paper>
  );
}
