import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "@mui/material";
import Dashboard from "../components/Dashboard";
import theme from "../theme";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: {
    list: vi.fn(),
    get: vi.fn(),
    savedAnalytics: vi.fn(),
    listMerchantMappings: vi.fn(),
    removeMerchantMapping: vi.fn(),
    statementExportUrl: vi.fn((id) => `/api/statements/${id}/export.csv`),
  },
}));

const report = (credits, debits) => ({
  analytics: {
    totals: { credits, debits },
    monthly: [{ month: "2026-10", credits, debits }],
    anomalies: [{ code: "large_debit", severity: "medium", message: "Large debit flagged." }],
    recurring: [{ merchant: "Monthly service", amount: debits, months: ["2026-09", "2026-10"] }],
  },
});

function setup(onNavigate = vi.fn()) {
  render(<ThemeProvider theme={theme}><Dashboard onNavigate={onNavigate} /></ThemeProvider>);
  return onNavigate;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listMerchantMappings.mockResolvedValue([]);
});

it("shows clear next steps when no statements have been saved", async () => {
  api.list.mockResolvedValue([]);
  const navigate = setup();
  expect(await screen.findByText(/no saved statements in this local database yet/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Review a statement" }));
  expect(navigate).toHaveBeenCalledWith("review");
});

it("keeps totals grouped by currency and shows saved insights and exports", async () => {
  api.list.mockResolvedValue([
    { id: 1, file_name: "inr.pdf", transaction_count: 2 },
    { id: 2, file_name: "usd.pdf", transaction_count: 3 },
  ]);
  api.get.mockImplementation(async (id) => ({
    statement: {
      header: { currency: id === 1 ? "INR" : "USD" },
      transactions: [{ category: id === 1 ? "Food" : "Transport", withdrawal: id === 1 ? "200.00" : "10.00" }],
    },
  }));
  api.savedAnalytics.mockImplementation(async (id) => id === 1 ? report("1000.00", "200.00") : report("50.00", "10.00"));
  const navigate = setup();

  expect(await screen.findByText("Income · INR")).toBeInTheDocument();
  expect(screen.getByText("Income · USD")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Monthly income and spending in INR" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Expense categories in USD" })).toBeInTheDocument();
  expect(screen.getByText("₹1,000.00")).toBeInTheDocument();
  expect(screen.getByText("$50.00")).toBeInTheDocument();
  expect(screen.getByText("Large debit flagged.")).toBeInTheDocument();
  expect(screen.getByText("Monthly service")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Export statement 2 CSV" })).toHaveAttribute("href", "/api/statements/2/export.csv");
  await userEvent.click(screen.getByRole("button", { name: "Open reconciliation" }));
  expect(navigate).toHaveBeenCalledWith("reconcile");
});

it("does not hide all results when one saved statement analysis fails", async () => {
  api.list.mockResolvedValue([{ id: 1, file_name: "broken.pdf", transaction_count: 1 }]);
  api.get.mockResolvedValue({ statement: { header: { currency: "INR" } } });
  api.savedAnalytics.mockRejectedValue(new Error("Unavailable"));
  setup();
  expect(await screen.findByText(/analysis request failed/i)).toBeInTheDocument();
  expect(screen.getByText("broken.pdf")).toBeInTheDocument();
});
