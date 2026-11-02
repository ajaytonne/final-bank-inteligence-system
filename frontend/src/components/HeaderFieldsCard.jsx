import { Checkbox, FormControlLabel, Grid, InputAdornment, Paper, TextField, Typography } from "@mui/material";
import ConfidenceChip from "./ConfidenceChip";
import { HEADER_FIELDS, fieldError } from "../utils/review";

export default function HeaderFieldsCard({ header, headerAck, onChange, onAck }) {
  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>
        Statement details
      </Typography>
      <Grid container spacing={2}>
        {HEADER_FIELDS.map(({ key, label, type }) => {
          const f = header[key];
          const flagged = f.needsReview && !headerAck[key];
          const err = fieldError(type, f.value);
          return (
            <Grid item xs={12} sm={6} md={4} key={key}>
              <TextField
                fullWidth
                size="small"
                label={label}
                type={type === "date" ? "date" : "text"}
                value={f.value}
                onChange={(e) => onChange(key, e.target.value)}
                error={Boolean(err)}
                helperText={err || f.note || (f.source === "none" ? "Not found — enter if known" : " ")}
                InputLabelProps={{ shrink: true }}
                inputProps={{ "aria-label": label, inputMode: type === "amount" ? "decimal" : undefined }}
                sx={flagged ? { "& .MuiOutlinedInput-root": { bgcolor: "warning.light" } } : undefined}
                InputProps={{
                  endAdornment: (
                    <InputAdornment position="end">
                      <ConfidenceChip confidence={f.confidence} source={f.source} note={f.note} missing={!f.original} />
                    </InputAdornment>
                  ),
                }}
              />
              {f.needsReview && (
                <FormControlLabel
                  sx={{ mt: -1 }}
                  control={<Checkbox size="small" checked={Boolean(headerAck[key])} onChange={(e) => onAck(key, e.target.checked)} />}
                  label={<Typography variant="caption">Verified against document</Typography>}
                />
              )}
            </Grid>
          );
        })}
      </Grid>
    </Paper>
  );
}
