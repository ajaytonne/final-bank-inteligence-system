import { ThemeProvider } from "@mui/material";
import App from "./App";
import { setApiBase } from "./api/client";
import defaultTheme from "./theme";

/**
 * The Statement Analyser as one component for another React app.
 *
 *   <StatementAnalyser apiBase="/statement-analyser" />
 *
 * apiBase  where the backend is mounted (see MODULE.md). Same origin as the host page, so no CORS setup is needed.
 * title    heading in the top bar.
 * theme    optional MUI theme; the module's own theme is used when omitted.
 * The host needs React 18 and MUI 6 (they are not bundled into the module).
 */
export function StatementAnalyser({ apiBase = "", title = "Statement Analyser", theme = defaultTheme }) {
  setApiBase(apiBase); // before the first render of the app, so its first request already goes to the right place
  return (
    <ThemeProvider theme={theme}>
      <App title={title} embedded />
    </ThemeProvider>
  );
}

export default StatementAnalyser;
