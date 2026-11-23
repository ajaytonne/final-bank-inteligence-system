// How a React host app uses the module (after: npm install ./statement-analyser-module, or copy dist-module/statement-analyser.js).
import StatementAnalyser from "./statement-analyser.js";

export default function StatementsPage() {
  // apiBase is where the host's backend mounted the module (see host_app.py)
  return <StatementAnalyser apiBase="/statement-analyser" title="Statement Analyser" />;
}
