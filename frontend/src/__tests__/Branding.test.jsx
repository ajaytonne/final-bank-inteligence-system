import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "@mui/material";
import theme from "../theme";
import App from "../App";
import { StatementAnalyser } from "../module";
import { Logo, Watermark } from "../components/Brand";

vi.mock("../api/client", () => ({
  setApiBase: vi.fn(),
  api: {
    health: vi.fn().mockResolvedValue({ status: "ok", tesseract_available: true, ollama_enabled: false, ollama_reachable: false }),
    list: vi.fn().mockResolvedValue([]),
    listAccounts: vi.fn().mockResolvedValue([]),
    listAssignments: vi.fn().mockResolvedValue([]),
    listRecon: vi.fn().mockResolvedValue([]),
  },
}));

const wrap = (ui) => render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);

it("shows the LIST logo and the product name in the header", async () => {
  wrap(<App />);
  const logo = screen.getByAltText("LIST");
  expect(logo.tagName).toBe("IMG");
  expect(logo.getAttribute("src")).toMatch(/^data:image\/png/); // inlined, so it also works when embedded in another app
  expect(screen.getByText("Statement Analyser")).toBeInTheDocument();
  await screen.findByText("OCR ready");
});

it("puts the logo behind the page as a mark that cannot be clicked", async () => {
  wrap(<App />);
  const mark = screen.getByTestId("watermark");
  expect(mark).toHaveAttribute("aria-hidden", "true");
  expect(getComputedStyle(mark).pointerEvents).toBe("none");
  await screen.findByText("OCR ready");
});

it("keeps the mark inside the module when embedded in another page", async () => {
  wrap(<StatementAnalyser apiBase="/x" title="Finance tools" />);
  expect(getComputedStyle(screen.getByTestId("watermark")).position).toBe("absolute");
  expect(screen.getByText("Finance tools")).toBeInTheDocument();
  await screen.findByText("OCR ready");
});

it("fills the whole screen with the mark when it is the main app", async () => {
  wrap(<App />);
  expect(getComputedStyle(screen.getByTestId("watermark")).position).toBe("fixed");
  await screen.findByText("OCR ready");
});

it("has a dark and a white logo", () => {
  const { rerender } = wrap(<Logo variant="dark" />);
  const dark = screen.getByAltText("LIST").getAttribute("src");
  rerender(<ThemeProvider theme={theme}><Logo variant="white" /></ThemeProvider>);
  expect(screen.getByAltText("LIST").getAttribute("src")).not.toBe(dark);
  rerender(<ThemeProvider theme={theme}><Watermark contained /></ThemeProvider>);
});
