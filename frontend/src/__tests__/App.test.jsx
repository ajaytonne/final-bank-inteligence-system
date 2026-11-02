import { render, screen, waitFor, within } from "@testing-library/react";
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
