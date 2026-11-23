import { Box } from "@mui/material";
// "?inline" puts the picture inside the code, so it also works when the screens are embedded in another app (no extra files to host).
import logoDark from "../assets/list-logo-dark.png?inline";
import logoWhite from "../assets/list-logo-white.png?inline";

/** The LIST logo. "dark" for light backgrounds, "white" for dark ones. */
export function Logo({ variant = "dark", height = 30, sx }) {
  return <Box component="img" src={variant === "white" ? logoWhite : logoDark} alt="LIST" sx={{ height, width: "auto", display: "block", ...sx }} />;
}

/** The logo as a faint background mark behind the page. `contained` keeps it inside its parent (when embedded in another app). */
export function Watermark({ contained = false }) {
  return (
    <Box
      aria-hidden
      data-testid="watermark"
      sx={{
        position: contained ? "absolute" : "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        backgroundImage: `url(${logoDark})`,
        backgroundRepeat: "no-repeat",
        backgroundPosition: "center 58%",
        backgroundSize: "min(62vw, 760px) auto",
        opacity: 0.07,
      }}
    />
  );
}
