import { Chip, Tooltip } from "@mui/material";
import { confidenceLevel } from "../utils/review";

const COLORS = { high: "success", medium: "info", low: "warning" };

export default function ConfidenceChip({ confidence, source, note, missing = false }) {
  if (missing) {
    return <Chip size="small" color="warning" variant="outlined" label="missing" />;
  }
  const level = confidenceLevel(confidence);
  const title = [
    `Review score ${(confidence * 100).toFixed(0)} (heuristic, not a probability)`,
    source && source !== "none" ? `Source: ${source.replace("_", " ")}` : null,
    note,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Tooltip title={title} arrow>
      <Chip
        size="small"
        variant="outlined"
        color={COLORS[level]}
        label={source === "llm" ? `AI ${Math.round(confidence * 100)}` : Math.round(confidence * 100)}
        data-testid="confidence-chip"
      />
    </Tooltip>
  );
}
