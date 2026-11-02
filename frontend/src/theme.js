import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#1f4e79" },
    secondary: { main: "#0f766e" },
    warning: { main: "#b45309", light: "#fef3c7" },
    background: { default: "#f4f6f9", paper: "#ffffff" },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Inter", "Segoe UI", Roboto, system-ui, sans-serif',
    h5: { fontWeight: 700 },
    subtitle2: { fontWeight: 600 },
  },
  components: {
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { border: "1px solid #e3e8ef" } } },
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { textTransform: "none", fontWeight: 600 } } },
    MuiTableCell: { styleOverrides: { root: { padding: "6px 8px" }, head: { fontWeight: 600, background: "#f8fafc" } } },
  },
});

export default theme;
