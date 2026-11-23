import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StatementAnalyser } from "../module";
import { setApiBase } from "../api/client";

const reply = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (String(url).endsWith("/api/health")) return reply({ status: "ok", tesseract_available: true, ollama_enabled: false, ollama_reachable: false });
    return reply([]);
  });
});

afterEach(() => setApiBase(""));

const urls = () => global.fetch.mock.calls.map(([u]) => String(u));

it("sends every request to the apiBase the host chose", async () => {
  render(<StatementAnalyser apiBase="/statement-analyser/" />);
  expect(await screen.findByText("OCR ready")).toBeInTheDocument();
  expect(urls()).toContain("/statement-analyser/api/health");
  expect(urls().every((u) => u.startsWith("/statement-analyser/api/"))).toBe(true);
});

it("uses the same origin when no apiBase is given", async () => {
  render(<StatementAnalyser />);
  await screen.findByText("OCR ready");
  expect(urls()).toContain("/api/health");
});

it("shows the host's title and the module's tabs", async () => {
  const user = userEvent.setup();
  render(<StatementAnalyser title="Finance tools" apiBase="/x" />);
  expect(screen.getByText("Finance tools")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Statement review" })).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => expect(urls()).toContain("/x/api/audit"));
});

it("works without the theme prop and with a custom one", async () => {
  const { createTheme } = await import("@mui/material");
  render(<StatementAnalyser theme={createTheme({ palette: { primary: { main: "#ff0000" } } })} />);
  await screen.findByText("OCR ready");
});
