import { createTheme } from "@mui/material/styles";

// Brand colours in one place. LIST's logo is black and white, so the interface is ink + one accent.
export const BRAND = { ink: "#111827", accent: "#0f766e", page: "#f3f4f7", line: "#e2e6ee" };

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: BRAND.ink },
    secondary: { main: BRAND.accent },
    warning: { main: "#b45309", light: "#fef3c7" },
    background: { default: BRAND.page, paper: "#ffffff" },
    text: { primary: BRAND.ink, secondary: "#4b5563" },
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: '"Inter", "Segoe UI", Roboto, system-ui, sans-serif',
    h5: { fontWeight: 700 },
    h6: { fontWeight: 700, letterSpacing: "-0.01em" },
    subtitle1: { fontWeight: 600 },
    subtitle2: { fontWeight: 600 },
  },
  components: {
    MuiPaper: {
      defaultProps: { elevation: 0 },
      // slightly see-through, so the logo in the background shows faintly between and behind the cards
      styleOverrides: { root: { border: `1px solid ${BRAND.line}`, backgroundColor: "rgba(255,255,255,0.93)", boxShadow: "0 1px 2px rgba(17,24,39,0.04)" } },
    },
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { textTransform: "none", fontWeight: 600, borderRadius: 10 } } },
    MuiTab: { styleOverrides: { root: { textTransform: "none", fontWeight: 600, fontSize: 15, minHeight: 48 } } },
    MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
    MuiAlert: { styleOverrides: { root: { borderRadius: 12 } } },
    MuiTableCell: { styleOverrides: { root: { padding: "6px 8px" }, head: { fontWeight: 600, background: "#f6f7fa" } } },
  },
});

export default theme;
