import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, List, ListItem, ListItemText } from "@mui/material";

// Shown before saving when the statement looks like a duplicate or overlaps one already saved.
export default function SaveWarningsDialog({ warnings, onSaveAnyway, onCancel }) {
  return (
    <Dialog open={Boolean(warnings)} onClose={onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>Check before saving</DialogTitle>
      <DialogContent>
        <Alert severity="warning" sx={{ mb: 1 }}>
          Nothing is blocked. Please check these points, then decide.
        </Alert>
        <List dense>
          {(warnings || []).map((w, i) => (
            <ListItem key={i} disableGutters>
              <ListItemText primary={w.message} />
            </ListItem>
          ))}
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Go back</Button>
        <Button variant="contained" color="secondary" onClick={onSaveAnyway}>Save anyway</Button>
      </DialogActions>
    </Dialog>
  );
}
