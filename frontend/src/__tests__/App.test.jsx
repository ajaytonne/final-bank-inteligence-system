import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "@mui/material";
import fixture from "./fixtures/extraction.json";
import theme from "../theme";
import App from "../App";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: {
    health: vi.fn(),
    extract: vi.fn(),
    save: vi.fn(),
    list: vi.fn(),
    get: vi.fn(),
    remove: vi.fn(),
  },
}));

const setup = () => {
  const user = userEvent.setup();
  render(
    <ThemeProvider theme={theme}>
      <App />
    </ThemeProvider>
  );
  return user;
};

const pdf = () => new File(["%PDF-1.4"], "statement.pdf", { type: "application/pdf" });

beforeEach(() => {
  vi.clearAllMocks();
  api.health.mockResolvedValue({ status: "ok", tesseract_available: true, ollama_enabled: false, ollama_reachable: false });
  api.list.mockResolvedValue([]);
  api.extract.mockResolvedValue(structuredClone(fixture));
  api.save.mockResolvedValue({ id: 7, created_at: "2026-10-29T00:00:00Z", statement: {} });
});

async function uploadAndExtract(user) {
  await user.upload(screen.getByTestId("file-input"), pdf());
  await user.click(screen.getByRole("button", { name: "Extract data" }));
  await screen.findByText("Statement details");
}

it("shows health chips", async () => {
  setup();
  expect(await screen.findByText("OCR ready")).toBeInTheDocument();
  expect(screen.getByText("Local LLM off")).toBeInTheDocument();
});

it("rejects unsupported files client-side", async () => {
  const user = userEvent.setup({ applyAccept: false });
  render(<App />);
  await user.upload(screen.getByTestId("file-input"), new File(["x"], "notes.txt", { type: "text/plain" }));
  expect(screen.getByText(/Unsupported file type/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Extract data" })).toBeDisabled();
  expect(api.extract).not.toHaveBeenCalled();
});

it("extracts, requires review of flagged rows, then saves", async () => {
  const user = setup();
  await uploadAndExtract(user);

  expect(api.extract).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Account holder")).toHaveValue("Priya Sharma");
  expect(screen.getAllByTestId(/^txn-row-/)).toHaveLength(8);
  expect(screen.getByTestId("review-chip")).toHaveTextContent("2 item(s) to review");
  expect(screen.getByTestId("row-warning-5")).toBeInTheDocument();

  const saveBtn = screen.getByRole("button", { name: "Save reviewed data" });
  expect(saveBtn).toBeDisabled();

  await user.click(screen.getByLabelText("Reviewed row 6"));
  await user.click(screen.getByLabelText("Reviewed row 7"));
  expect(screen.getByTestId("review-chip")).toHaveTextContent("All flagged items reviewed");
  expect(saveBtn).toBeEnabled();

  await user.click(saveBtn);
  await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
  const payload = api.save.mock.calls[0][0];
  expect(payload.transactions).toHaveLength(8);
  expect(payload.header.account_number_masked).toBe("XXXXXXXX1234");
  expect(await screen.findByText("Saved statement #7")).toBeInTheDocument();
});

it("editing a flagged cell acknowledges it and rechecks balance", async () => {
  const user = setup();
  await uploadAndExtract(user);
  const row = screen.getByTestId("txn-row-5");
  const balance = within(row).getAllByRole("textbox").at(-1);
  await user.clear(balance);
  await user.type(balance, "114861.41");
  expect(screen.queryByTestId("row-warning-6")).not.toBeInTheDocument();
  expect(screen.getByTestId("open-items")).toHaveTextContent("Row 7");
  expect(screen.getByTestId("open-items")).not.toHaveTextContent("Row 6");
});

it("blocks save on invalid edits", async () => {
  const user = setup();
  await uploadAndExtract(user);
  await user.click(screen.getByLabelText("Reviewed row 6"));
  await user.click(screen.getByLabelText("Reviewed row 7"));
  const acct = screen.getByLabelText("Account number (masked)");
  await user.clear(acct);
  await user.type(acct, "123456781234");
  expect(screen.getByRole("button", { name: "Save reviewed data" })).toBeDisabled();
  expect(screen.getByText(/at most 4 digits/)).toBeInTheDocument();
});

it("deletes and adds rows", async () => {
  const user = setup();
  await uploadAndExtract(user);
  await user.click(screen.getByLabelText("Delete row 1"));
  expect(screen.getAllByTestId(/^txn-row-/)).toHaveLength(7);
  await user.click(screen.getByRole("button", { name: "Add row" }));
  expect(screen.getAllByTestId(/^txn-row-/)).toHaveLength(8);
  expect(screen.getByTestId("open-items")).toHaveTextContent("Row 8");
});

it("shows server errors", async () => {
  api.extract.mockRejectedValueOnce(new Error("File extension does not match its content."));
  const user = setup();
  await user.upload(screen.getByTestId("file-input"), pdf());
  await user.click(screen.getByRole("button", { name: "Extract data" }));
  expect(await screen.findByText("File extension does not match its content.")).toBeInTheDocument();
});

describe("financial summary", () => {
  it("shows income, expenses, savings and the top expense category", async () => {
    const user = setup();
    await uploadAndExtract(user);
    expect(screen.getByText("Smart Financial Summary")).toBeInTheDocument();
    expect(screen.getByTestId("summary-income")).toHaveTextContent("₹1,10,802.01");
    expect(screen.getByTestId("summary-expenses")).toHaveTextContent("₹21,831.50");
    expect(screen.getByTestId("summary-savings")).toHaveTextContent("₹88,970.51");
    expect(screen.getByTestId("summary-savings")).toHaveStyle({ color: "rgb(46, 125, 50)" }); // green
    expect(screen.getByTestId("summary-top-category")).toHaveTextContent("Top Expense Category: Bills – ₹15,977.47");
  });

  it("updates when a row is deleted", async () => {
    const user = setup();
    await uploadAndExtract(user);
    await user.click(screen.getByLabelText("Delete row 1")); // a 55,000 salary deposit
    expect(screen.getByTestId("summary-income")).toHaveTextContent("₹55,802.01");
    expect(screen.getByTestId("summary-savings")).toHaveTextContent("₹33,970.51");
  });

  it("shows negative savings in red", async () => {
    const user = setup();
    await uploadAndExtract(user);
    // Remove every deposit row so only expenses are left.
    for (const n of [1, 1, 4, 5]) await user.click(screen.getByLabelText(`Delete row ${n}`));
    expect(screen.getAllByTestId(/^txn-row-/)).toHaveLength(4);
    expect(screen.getByTestId("summary-income")).toHaveTextContent("₹0.00");
    expect(screen.getByTestId("summary-savings")).toHaveTextContent("-₹21,831.50");
    expect(screen.getByTestId("summary-savings")).toHaveStyle({ color: "rgb(211, 47, 47)" }); // red
  });
});

describe("categories", () => {
  const categoryOf = (n) => screen.getByLabelText(`Category row ${n}`);

  it("shows a detected category and an Income / Expense label for each row", async () => {
    const user = setup();
    await uploadAndExtract(user);
    const shown = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => categoryOf(n).value);
    expect(shown).toEqual(["Salary", "Salary", "Other", "Bills", "Food", "Shopping", "Bills", "Other"]);
    expect(within(screen.getByTestId("txn-row-0")).getByText("Income")).toBeInTheDocument();
    expect(within(screen.getByTestId("txn-row-2")).getByText("Expense")).toBeInTheDocument();
  });

  it("picks a category for a new row from its description, and keeps a manual choice", async () => {
    const user = setup();
    await uploadAndExtract(user);
    await user.click(screen.getByRole("button", { name: "Add row" }));
    const description = within(screen.getByTestId("txn-row-8")).getAllByRole("textbox")[0];
    expect(categoryOf(9)).toHaveValue("Other");

    await user.type(description, "Swiggy lunch order");
    expect(categoryOf(9)).toHaveValue("Food");

    await user.selectOptions(categoryOf(9), "Entertainment"); // manual choice
    await user.type(description, " zomato");
    expect(categoryOf(9)).toHaveValue("Entertainment"); // not overridden
  });

  it("does not replace the category of an existing row when its description is edited", async () => {
    const user = setup();
    await uploadAndExtract(user);
    expect(categoryOf(5)).toHaveValue("Food");
    const description = within(screen.getByTestId("txn-row-4")).getAllByRole("textbox")[0];
    await user.clear(description);
    await user.type(description, "Amazon order");
    expect(categoryOf(5)).toHaveValue("Food");
  });

  it("saves the chosen category with each transaction", async () => {
    const user = setup();
    await uploadAndExtract(user);
    await user.selectOptions(categoryOf(3), "Health");
    await user.click(screen.getByLabelText("Reviewed row 6"));
    await user.click(screen.getByLabelText("Reviewed row 7"));
    await user.click(screen.getByRole("button", { name: "Save reviewed data" }));
    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    const { transactions } = api.save.mock.calls[0][0];
    expect(transactions.map((t) => t.category)).toEqual(["Salary", "Salary", "Health", "Bills", "Food", "Shopping", "Bills", "Other"]);
  });
});

describe("search and filter", () => {
  const count = () => screen.getByTestId("filter-count");
  const rowsShown = () => screen.queryAllByTestId(/^txn-row-/).length;

  it("shows everything at first", async () => {
    const user = setup();
    await uploadAndExtract(user);
    expect(count()).toHaveTextContent("Showing 8 of 8 transactions");
    expect(screen.getByRole("button", { name: "Clear Filters" })).toBeDisabled();
  });

  it("searches descriptions (partial, any case) and the summary follows", async () => {
    const user = setup();
    await uploadAndExtract(user);
    await user.type(screen.getByLabelText("Search description"), "AMAZ");
    expect(count()).toHaveTextContent("Showing 1 of 8 transactions");
    expect(rowsShown()).toBe(1);
    expect(screen.getByTestId("txn-row-5")).toBeInTheDocument(); // keeps its original row number
    expect(screen.getByTestId("summary-income")).toHaveTextContent("₹715.44");
    expect(screen.getByTestId("summary-expenses")).toHaveTextContent("₹0.00");
    expect(screen.getByText(/Based on the 1 of 8 transactions/)).toBeInTheDocument();
  });

  it("filters by date range, amount range, type and category", async () => {
    const user = setup();
    await uploadAndExtract(user);

    fireEvent.change(screen.getByLabelText("From Date"), { target: { value: "2026-09-05" } });
    fireEvent.change(screen.getByLabelText("To Date"), { target: { value: "2026-09-08" } });
    expect(rowsShown()).toBe(4); // 5th, 6th, 7th and 8th September

    await user.type(screen.getByLabelText("Minimum amount"), "1000");
    await user.type(screen.getByLabelText("Maximum amount"), "5000");
    expect(count()).toHaveTextContent("Showing 2 of 8 transactions"); // 3,917.26 and 1,936.77

    await user.selectOptions(screen.getByLabelText("Type"), "Income");
    expect(screen.getByText(/No transactions found/)).toBeInTheDocument();
    expect(count()).toHaveTextContent("Showing 0 of 8 transactions");

    await user.selectOptions(screen.getByLabelText("Type"), "Expense");
    await user.selectOptions(screen.getByLabelText("Category"), "Food");
    expect(rowsShown()).toBe(1);
    expect(screen.getByTestId("txn-row-4")).toBeInTheDocument();
  });

  it("combines every filter, and Clear Filters resets them all", async () => {
    const user = setup();
    await uploadAndExtract(user);
    await user.type(screen.getByLabelText("Search description"), "upi");
    fireEvent.change(screen.getByLabelText("From Date"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("To Date"), { target: { value: "2026-09-30" } });
    await user.type(screen.getByLabelText("Minimum amount"), "100");
    await user.type(screen.getByLabelText("Maximum amount"), "5000");
    await user.selectOptions(screen.getByLabelText("Type"), "Expense");
    await user.selectOptions(screen.getByLabelText("Category"), "Food");
    expect(count()).toHaveTextContent("Showing 1 of 8 transactions");

    await user.click(screen.getByRole("button", { name: "Clear Filters" }));
    expect(count()).toHaveTextContent("Showing 8 of 8 transactions");
    expect(rowsShown()).toBe(8);
    expect(screen.getByLabelText("Search description")).toHaveValue("");
    expect(screen.getByLabelText("From Date")).toHaveValue("");
    expect(screen.getByLabelText("Minimum amount")).toHaveValue(null);
    expect(screen.getByLabelText("Type")).toHaveValue("All");
    expect(screen.getByLabelText("Category")).toHaveValue("All");
    expect(screen.getByRole("button", { name: "Clear Filters" })).toBeDisabled();
  });

  it("clears the filters when a row is added so the new row is visible", async () => {
    const user = setup();
    await uploadAndExtract(user);
    await user.type(screen.getByLabelText("Search description"), "amaz");
    await user.click(screen.getByRole("button", { name: "Add row" }));
    expect(count()).toHaveTextContent("Showing 9 of 9 transactions");
    expect(screen.getByTestId("txn-row-8")).toBeInTheDocument();
  });
});
