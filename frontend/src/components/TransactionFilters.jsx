import { Box, Button, InputAdornment, Paper, Stack, TextField, Typography } from "@mui/material";
import { CATEGORIES, EMPTY_FILTERS, hasFilters } from "../utils/review";

/** Search & Filter controls. All state lives in App; this only shows it and reports changes. */
export default function TransactionFilters({ filters, onChange, shown, total }) {
  const set = (key) => (e) => onChange({ ...filters, [key]: e.target.value });

  const text = (key, label, props) => (
    <TextField
      size="small"
      label={label}
      value={filters[key]}
      onChange={set(key)}
      InputLabelProps={{ shrink: true }}
      inputProps={{ "aria-label": label }}
      {...props}
    />
  );
  const dropdown = (key, label, options) =>
    text(key, label, {
      select: true,
      SelectProps: { native: true },
      children: options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      )),
    });
  const amount = (key, label) =>
    text(key, label, {
      type: "number",
      inputProps: { "aria-label": label, min: 0, step: "any" },
      InputProps: { startAdornment: <InputAdornment position="start">₹</InputAdornment> },
    });

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>
        Search &amp; Filter
      </Typography>
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)", md: "repeat(4, 1fr)" } }}>
        {text("search", "Search description", { placeholder: "e.g. swiggy" })}
        {text("from", "From Date", { type: "date" })}
        {text("to", "To Date", { type: "date" })}
        {dropdown("type", "Type", ["All", "Income", "Expense"])}
        {amount("min", "Minimum amount")}
        {amount("max", "Maximum amount")}
        {dropdown("category", "Category", ["All", ...CATEGORIES])}
        <Button variant="outlined" disabled={!hasFilters(filters)} onClick={() => onChange(EMPTY_FILTERS)}>
          Clear Filters
        </Button>
      </Box>
      <Stack sx={{ mt: 1.5 }}>
        <Typography variant="body2" color="text.secondary" data-testid="filter-count">
          Showing {shown} of {total} transaction{total === 1 ? "" : "s"}
        </Typography>
      </Stack>
    </Paper>
  );
}
