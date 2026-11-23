import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "@mui/material";
import theme from "../theme";
import Reconciliation from "../components/Reconciliation";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: {
    list: vi.fn(), listAccounts: vi.fn(), createAccount: vi.fn(), updateAccount: vi.fn(), listAssignments: vi.fn(), assignStatement: vi.fn(),
    createRecon: vi.fn(), runRecon: vi.fn(), listRecon: vi.fn(), getRecon: vi.fn(), removeRecon: vi.fn(),
    confirmMatch: vi.fn(), rejectMatch: vi.fn(), consolidated: vi.fn(), exportUrl: (id) => `/api/reconciliations/${id}/export`,
  },
}));

const snap = (description, amount, direction, reference = "") => ({ date: "2026-09-05", description, reference, amount, direction });
const match = (over) => ({
  id: 1, session_id: 5, a_statement_id: 1, a_index: 0, b_statement_id: 2, b_index: 0, match_type: "Reference", status: "Matched",
  reason: "Same reference UTR1.", confidence: 0.98, confirmation_status: "auto", internal_transfer: false, note: null,
  a: snap("NEFT TO HDFC", "10000.00", "debit", "UTR1"), b: snap("NEFT FROM SBI", "10000.00", "credit", "UTR1"), ...over,
});
const summary = {
  total_a: 3, total_b: 3, matched: 1, timing_differences: 0, possible_matches: 1, manual_review: 0, unmatched: 2, period_gaps: 0,
  missing_transactions: 0, duplicate_candidates: 0, rejected: 0, confirmed_internal_transfers: 0, total_matched_amount: "10000.00", total_unmatched_amount: "5350.00",
};
const session = { id: 5, kind: "inter_bank", statement_a_id: 1, statement_b_id: 2, a_label: "sbi.pdf", b_label: "hdfc.pdf", date_window_days: 2, status: "completed", total_a: 3, total_b: 3, notes: ["Statement A covers 2026-09-01 to 2026-09-30."], created_at: "2026-11-20T00:00:00Z", updated_at: "2026-11-20T00:00:00Z" };
const possible = match({ id: 2, status: "Possible Match", match_type: "Amount only", confidence: 0.35, confirmation_status: "pending", reason: "Same amount ₹777.00; amount alone is not enough.", a: snap("RENT", "777.00", "debit"), b: snap("SALARY", "777.00", "credit") });
const detail = (matches = [match(), possible], sum = summary) => ({ session, summary: sum, matches });

const setup = () => {
  const user = userEvent.setup();
  render(<ThemeProvider theme={theme}><Reconciliation /></ThemeProvider>);
  return user;
};

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([{ id: 1, file_name: "sbi.pdf", transaction_count: 3, account_holder: "A" }, { id: 2, file_name: "hdfc.pdf", transaction_count: 3, account_holder: "A" }]);
  api.listAccounts.mockResolvedValue([]);
  api.listAssignments.mockResolvedValue([]);
  api.listRecon.mockResolvedValue([]);
  api.createRecon.mockResolvedValue(session);
  api.runRecon.mockResolvedValue(detail());
  api.consolidated.mockResolvedValue({ income: "15777.00", expenses: "11127.00", savings: "4650.00", excluded_transfer_count: 0, excluded_amount: "0.00" });
});

async function start(user) {
  await screen.findByRole("option", { name: "#1 sbi.pdf", selected: false, hidden: true }).catch(() => null);
  await waitFor(() => expect(screen.getAllByRole("option", { name: "#1 sbi.pdf" }).length).toBeGreaterThan(0));
  await user.selectOptions(screen.getByLabelText("Statement A"), "1");
  await user.selectOptions(screen.getByLabelText("Statement B"), "2");
  await user.click(screen.getByRole("button", { name: "Start reconciliation" }));
}

it("needs two statements before it can start", async () => {
  const user = setup();
  const startBtn = screen.getByRole("button", { name: "Start reconciliation" });
  expect(startBtn).toBeDisabled();
  await waitFor(() => expect(screen.getAllByRole("option", { name: "#1 sbi.pdf" }).length).toBeGreaterThan(0));
  await user.selectOptions(screen.getByLabelText("Statement A"), "1");
  expect(startBtn).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Statement B"), "2");
  expect(startBtn).toBeEnabled();
});

it("picks a sensible date window for each type", async () => {
  const user = setup();
  expect(screen.getByLabelText("Allowed date difference")).toHaveValue("2");
  await user.selectOptions(screen.getByLabelText("Reconciliation type"), "internal");
  expect(screen.getByLabelText("Allowed date difference")).toHaveValue("0");
});

it("starts a reconciliation and shows summary, notes and the review list first", async () => {
  const user = setup();
  await start(user);
  await waitFor(() => expect(api.createRecon).toHaveBeenCalledWith({ kind: "inter_bank", statement_a_id: 1, statement_b_id: 2, date_window_days: 2 }));
  expect(api.runRecon).toHaveBeenCalledWith(5);
  expect(await screen.findByText(/Statement A covers 2026-09-01/)).toBeInTheDocument();
  expect(screen.getByTestId("sum-Matched")).toHaveTextContent("1");
  expect(screen.getByTestId("sum-Total matched amount")).toHaveTextContent("₹10,000.00");
  expect(screen.getByTestId("sum-Total unmatched amount")).toHaveTextContent("₹5,350.00");
  expect(screen.getByTestId("consolidated")).toHaveTextContent("savings ₹4,650.00");
  expect(screen.getByRole("tab", { name: "Needs review (1)" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText(/amount alone is not enough/)).toBeInTheDocument(); // the possible match, with its reason
  expect(screen.queryByText("NEFT TO HDFC")).not.toBeInTheDocument(); // the matched pair is on another tab
  await user.click(screen.getByRole("tab", { name: "Matched (1)" }));
  const row = screen.getByTestId("recon-row-1");
  expect(within(row).getByText("NEFT TO HDFC")).toBeInTheDocument();
  expect(within(row).getByText(/₹10,000.00 Dr/)).toBeInTheDocument();
  expect(within(row).getByText("98%")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Export CSV/ })).toHaveAttribute("href", "/api/reconciliations/5/export");
});

it("confirms a possible match only when the user clicks", async () => {
  const confirmed = { ...possible, status: "Matched", confirmation_status: "confirmed" };
  api.confirmMatch.mockResolvedValue(detail([match(), confirmed], { ...summary, matched: 2, possible_matches: 0 }));
  const user = setup();
  await start(user);
  await screen.findByTestId("recon-row-2");
  expect(api.confirmMatch).not.toHaveBeenCalled(); // never automatic
  await user.click(screen.getByRole("button", { name: "Confirm match 2" }));
  expect(api.confirmMatch).toHaveBeenCalledWith(5, 2);
  expect(await screen.findByTestId("sum-Matched")).toHaveTextContent("2");
});

it("rejects a match and shows server refusals", async () => {
  api.rejectMatch.mockResolvedValue(detail([match(), { ...possible, status: "Rejected Match", confirmation_status: "rejected" }], { ...summary, possible_matches: 0, rejected: 1 }));
  const user = setup();
  await start(user);
  await user.click(await screen.findByRole("button", { name: "Reject match 2" }));
  expect(api.rejectMatch).toHaveBeenCalledWith(5, 2);
  await waitFor(() => expect(screen.getByRole("tab", { name: "Rejected (1)" })).toBeInTheDocument());

  api.confirmMatch.mockRejectedValueOnce(new Error("Transaction 1 of statement 2 already belongs to another matched pair (#1). Reject that pair first."));
  await user.click(screen.getByRole("tab", { name: "Matched (1)" }));
  await user.click(screen.getByRole("button", { name: "Confirm match 1" }));
  expect(await screen.findByText(/already belongs to another matched pair/)).toBeInTheDocument();
});

it("marks a possible transfer between own accounts and lets the user confirm it", async () => {
  const transfer = match({ internal_transfer: true });
  api.runRecon.mockResolvedValue(detail([transfer], { ...summary, possible_matches: 0 }));
  api.confirmMatch.mockResolvedValue(detail([{ ...transfer, confirmation_status: "confirmed" }], { ...summary, possible_matches: 0, confirmed_internal_transfers: 1 }));
  api.consolidated
    .mockResolvedValueOnce({ income: "15777.00", expenses: "11127.00", savings: "4650.00", excluded_transfer_count: 0, excluded_amount: "0.00" })
    .mockResolvedValueOnce({ income: "5777.00", expenses: "1127.00", savings: "4650.00", excluded_transfer_count: 1, excluded_amount: "10000.00" });
  const user = setup();
  await start(user);
  expect(await screen.findByText("Possible own-account transfer")).toBeInTheDocument();
  expect(screen.getByTestId("consolidated")).toHaveTextContent("no confirmed transfers between your own accounts are left out");
  await user.click(screen.getByRole("button", { name: "Confirm match 1" }));
  expect(await screen.findByText("Own-account transfer (confirmed)")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByTestId("consolidated")).toHaveTextContent("1 confirmed transfer(s) between your own accounts, ₹10,000.00, left out"));
  expect(screen.getByTestId("sum-Confirmed internal transfers")).toHaveTextContent("1");
});

it("reopens an earlier reconciliation", async () => {
  api.listRecon.mockResolvedValue([session]);
  api.getRecon.mockResolvedValue(detail());
  const user = setup();
  await user.click(await screen.findByRole("button", { name: "Open reconciliation 5" }));
  expect(api.getRecon).toHaveBeenCalledWith(5);
  expect(await screen.findByTestId("sum-Matched")).toBeInTheDocument();
});

it("shows an error when the reconciliation cannot start", async () => {
  api.createRecon.mockRejectedValueOnce(new Error("Internal reconciliation needs two statements from the same bank account."));
  const user = setup();
  await start(user);
  expect(await screen.findByText(/same bank account/)).toBeInTheDocument();
  expect(api.runRecon).not.toHaveBeenCalled();
});

describe("bank accounts", () => {
  it("adds an account and links a statement to it", async () => {
    api.createAccount.mockResolvedValue({ id: 9 });
    const user = setup();
    await user.type(screen.getByLabelText("Bank name"), "SBI");
    await user.type(screen.getByLabelText("Account name"), "SBI Savings");
    await user.click(screen.getByLabelText("This is my own account"));
    api.listAccounts.mockResolvedValue([{ id: 9, bank_name: "SBI", account_label: "SBI Savings", account_number_masked: null, ownership_confirmed: true }]);
    await user.click(screen.getByRole("button", { name: "Add account" }));
    expect(api.createAccount).toHaveBeenCalledWith({ bank_name: "SBI", account_label: "SBI Savings", account_number_masked: null, ownership_confirmed: true });
    expect(await screen.findByText("SBI Savings", { selector: "strong" })).toBeInTheDocument();

    api.assignStatement.mockResolvedValue({ statement_id: 1, account_id: 9 });
    await user.selectOptions(await screen.findByLabelText("Account for statement 1"), "9");
    expect(api.assignStatement).toHaveBeenCalledWith(1, 9);
  });

  it("changes whether an account is the user's own", async () => {
    api.listAccounts.mockResolvedValue([{ id: 9, bank_name: "SBI", account_label: "SBI Savings", account_number_masked: "XXXX1111", ownership_confirmed: false }]);
    api.updateAccount.mockResolvedValue({});
    const user = setup();
    await user.click(await screen.findByLabelText("Mine: SBI Savings"));
    expect(api.updateAccount).toHaveBeenCalledWith(9, { ownership_confirmed: true });
  });
});
