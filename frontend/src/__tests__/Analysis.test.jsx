import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "@mui/material";
import theme from "../theme";
import Analysis from "../components/Analysis";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { list: vi.fn(), analyse: vi.fn(), savedAnalytics: vi.fn() } }));

const analytics = {
  period: { start: "2026-07-01", end: "2026-08-20" },
  transaction_count: 8,
  totals: { credits: "180000.00", debits: "36500.00", credit_count: 4, debit_count: 4, net: "143500.00" },
  monthly: [{ month: "2026-07", credits: "130000.00", debits: "28000.00", net: "102000.00", average_balance: "94967.74", min_balance: "52000.00", max_balance: "112000.00" }],
  balances: { average_daily_balance: "114029.41", min_balance: "52000.00", max_balance: "150000.00", closing_balance: "141500.00" },
  salary: { detected: true, average_amount: "50000.00", months_with_salary: 2, months_in_period: 2, regularity: 1 },
  emi: { obligations: [{ narration: "NACH DR HDFC LOAN EMI", amount: "8000.00", months: ["2026-07", "2026-08"], count: 2, basis: "labelled as EMI/NACH and repeats", rows: [2, 7] }], monthly_obligation: "8000.00", obligation_to_salary: 0.16 },
  bounces: { count: 1, events: [{ row: 8, date: "2026-08-20", amount: "500.00", direction: "debit", description: "CHQ RETURN INSUFFICIENT FUNDS" }] },
  cash: { deposits_total: "60000.00", deposit_count: 1, large_deposits: [{ row: 3, date: "2026-07-10", amount: "60000.00" }], large_deposit_threshold: "50000.00" },
  circular: { count: 1, pairs: [{ out_row: 4, in_row: 5, amount: "20000.00", party: ["ramesh", "kumar"], days_apart: 1 }] },
};
const full = {
  file_name: "march.pdf",
  bank: { name: "HDFC Bank", code: "HDFC", source: "ifsc" },
  analytics,
  tamper: { status: "suspicious", flags: [], note: "Warning signs only." },
  flags: [
    { level: "high", code: "tamper_editor_software", message: "The file was produced by 'iLovePDF'." },
    { level: "medium", code: "bounces", message: "1 bounced or returned item(s)." },
  ],
};

const setup = () => {
  render(<ThemeProvider theme={theme}><Analysis /></ThemeProvider>);
  return userEvent.setup();
};
const pdf = () => new File(["%PDF-1.4"], "march.pdf", { type: "application/pdf" });

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([]);
  api.analyse.mockResolvedValue(full);
});

it("analyses an uploaded file and shows the findings in plain words", async () => {
  const user = setup();
  expect(screen.getByRole("button", { name: "Analyse file" })).toBeDisabled();
  await user.upload(screen.getByTestId("analysis-file"), pdf());
  await user.click(screen.getByRole("button", { name: "Analyse file" }));
  const result = await screen.findByTestId("analysis-result");
  expect(api.analyse).toHaveBeenCalledWith(expect.objectContaining({ name: "march.pdf" }), "");
  expect(within(result).getByText("Bank: HDFC Bank")).toBeInTheDocument();
  expect(screen.getByTestId("tamper-chip")).toHaveTextContent("Possible tampering");
  expect(screen.getByTestId("card-avg")).toHaveTextContent("₹1,14,029.41");
  expect(screen.getByTestId("card-salary")).toHaveTextContent("₹50,000.00");
  expect(screen.getByTestId("card-emi")).toHaveTextContent("₹8,000.00");
  expect(screen.getByText("16% of salary")).toBeInTheDocument();
  expect(screen.getByTestId("card-bounces")).toHaveTextContent("1");
  expect(screen.getByText("Row 8 · 2026-08-20 · bounced/returned · ₹500.00 · CHQ RETURN INSUFFICIENT FUNDS")).toBeInTheDocument();
  expect(screen.getByText(/Rows 4 and 5 · ₹20,000.00 out and back \(ramesh kumar\) after 1 day/)).toBeInTheDocument();
  expect(within(screen.getByTestId("monthly")).getByText("2026-07")).toBeInTheDocument();
});

it("lists the high severity flag before the medium one", async () => {
  const user = setup();
  await user.upload(screen.getByTestId("analysis-file"), pdf());
  await user.click(screen.getByRole("button", { name: "Analyse file" }));
  const flags = await screen.findByTestId("flags");
  const text = within(flags).getAllByRole("alert").map((a) => a.textContent);
  expect(text[0]).toMatch(/iLovePDF/);
  expect(text[1]).toMatch(/bounced/);
});

it("sends the password for a locked PDF", async () => {
  const user = setup();
  await user.upload(screen.getByTestId("analysis-file"), pdf());
  await user.type(screen.getByLabelText("PDF password (only if locked)"), "secret");
  await user.click(screen.getByRole("button", { name: "Analyse file" }));
  await waitFor(() => expect(api.analyse).toHaveBeenCalledWith(expect.anything(), "secret"));
});

it("shows the server's message when the analysis fails", async () => {
  api.analyse.mockRejectedValue(new Error("PDF is password protected. Provide the password."));
  const user = setup();
  await user.upload(screen.getByTestId("analysis-file"), pdf());
  await user.click(screen.getByRole("button", { name: "Analyse file" }));
  expect(await screen.findByText("PDF is password protected. Provide the password.")).toBeInTheDocument();
  expect(screen.queryByTestId("analysis-result")).not.toBeInTheDocument();
});

it("refuses an unsupported file before calling the server", async () => {
  const user = userEvent.setup({ applyAccept: false });
  render(<ThemeProvider theme={theme}><Analysis /></ThemeProvider>);
  await user.upload(screen.getByTestId("analysis-file"), new File(["x"], "notes.txt", { type: "text/plain" }));
  expect(screen.getByText(/Unsupported file type/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Analyse file" })).toBeDisabled();
  expect(api.analyse).not.toHaveBeenCalled();
});

it("analyses a saved statement, which has no file checks", async () => {
  api.list.mockResolvedValue([{ id: 5, file_name: "saved.pdf", account_holder: "P", transaction_count: 8, created_at: "2026-11-01T00:00:00Z" }]);
  api.savedAnalytics.mockResolvedValue({ ...full, file_name: "saved.pdf", tamper: null, flags: [] });
  const user = setup();
  await user.selectOptions(await screen.findByLabelText("Saved statement"), "5");
  await user.click(screen.getByRole("button", { name: "Analyse saved statement" }));
  expect(await screen.findByText("Nothing unusual was found.")).toBeInTheDocument();
  expect(api.savedAnalytics).toHaveBeenCalledWith("5");
  expect(screen.queryByTestId("tamper-chip")).not.toBeInTheDocument();
});

it("handles a statement with no balances or salary", async () => {
  api.analyse.mockResolvedValue({
    ...full, flags: [], tamper: { status: "unavailable", flags: [], note: "Images have no file trail to check." },
    analytics: { ...analytics, balances: null, monthly: [], salary: { detected: false }, emi: { obligations: [], monthly_obligation: "0.00", obligation_to_salary: null },
      bounces: { count: 0, events: [] }, cash: { deposits_total: "0.00", large_deposits: [] }, circular: { count: 0, pairs: [] } },
  });
  const user = setup();
  await user.upload(screen.getByTestId("analysis-file"), pdf());
  await user.click(screen.getByRole("button", { name: "Analyse file" }));
  expect(await screen.findByTestId("card-salary")).toHaveTextContent("Not found");
  expect(screen.getByText("No balances in the statement")).toBeInTheDocument();
  expect(screen.getByTestId("tamper-chip")).toHaveTextContent("File trail not checked");
  expect(screen.queryByTestId("monthly")).not.toBeInTheDocument();
});
