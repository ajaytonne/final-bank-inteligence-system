import { useRef, useState } from "react";
import { Alert, Box, Button, LinearProgress, Paper, Stack, Typography } from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { ACCEPTED_EXT, MAX_UPLOAD_MB, validateClientFile } from "../utils/review";

export default function UploadPanel({ onExtract, loading, error }) {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [localError, setLocalError] = useState(null);
  const [drag, setDrag] = useState(false);

  const choose = (f) => {
    const err = validateClientFile(f);
    setLocalError(err);
    setFile(err ? null : f);
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDrag(false);
    if (e.dataTransfer.files?.[0]) choose(e.dataTransfer.files[0]);
  };

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="subtitle2" gutterBottom>
        Upload a dummy bank statement
      </Typography>
      <Box
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        sx={{
          border: "2px dashed",
          borderColor: drag ? "primary.main" : "#cbd5e1",
          bgcolor: drag ? "#eef4fb" : "#fafbfc",
          borderRadius: 2,
          p: 4,
          textAlign: "center",
          cursor: "pointer",
        }}
      >
        <UploadFileIcon color="primary" sx={{ fontSize: 40 }} />
        <Typography>{file ? file.name : "Drag a PDF or image here, or click to browse"}</Typography>
        <Typography variant="caption" color="text.secondary">
          {ACCEPTED_EXT.join(" ")} · up to {MAX_UPLOAD_MB} MB
        </Typography>
        <input
          ref={inputRef}
          data-testid="file-input"
          type="file"
          hidden
          accept={ACCEPTED_EXT.join(",")}
          onChange={(e) => choose(e.target.files?.[0])}
        />
      </Box>
      <Stack direction="row" spacing={2} sx={{ mt: 2 }} alignItems="center">
        <Button variant="contained" disabled={!file || loading} onClick={() => onExtract(file)}>
          {loading ? "Extracting…" : "Extract data"}
        </Button>
        {file && !loading && (
          <Typography variant="body2" color="text.secondary">
            {(file.size / 1024).toFixed(0)} KB
          </Typography>
        )}
      </Stack>
      {loading && <LinearProgress sx={{ mt: 2 }} />}
      {(localError || error) && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {localError || error}
        </Alert>
      )}
    </Paper>
  );
}
