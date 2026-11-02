import fixture from "./fixtures/extraction.json";
import {
  buildSavePayload,
  checkBalances,
  confidenceLevel,
  emptyRow,
  formatAmount,
  openReviewItems,
  toReviewState,
  validateClientFile,
  validationErrors,
} from "../utils/review";

const file = (name, size = 100) => ({ name, size });

describe("validateClientFile", () => {
  it("accepts pdf and images", () => {
    expect(validateClientFile(file("a.pdf"))).toBeNull();
    expect(validateClientFile(file("SCAN.JPG"))).toBeNull();
  });
  it("rejects bad input", () => {
    expect(validateClientFile(null)).toMatch(/Choose/);
    expect(validateClientFile(file("a.txt"))).toMatch(/Unsupported/);
    expect(validateClientFile(file("noext"))).toMatch(/Unsupported/);
    expect(validateClientFile(file("a.pdf", 0))).toMatch(/empty/);
    expect(validateClientFile(file("a.pdf", 11 * 1024 * 1024))).toMatch(/exceeds/);
  });
});

it("confidenceLevel buckets", () => {
  expect(confidenceLevel(0.95)).toBe("high");
  expect(confidenceLevel(0.8)).toBe("medium");
  expect(confidenceLevel(0.5)).toBe("low");
});

it("formatAmount uses Indian grouping", () => {
  expect(formatAmount("135000.00")).toBe("1,35,000.00");
  expect(formatAmount(null)).toBe("");
  expect(formatAmount("abc")).toBe("abc");
});

describe("review state", () => {
  let state;
  beforeEach(() => {
    state = toReviewState(fixture);
  });

  it("maps extraction to editable strings", () => {
    expect(state.header.account_holder.value).toBe("Priya Sharma");
    expect(state.header.opening_balance.value).toBe("25000.00");
    expect(state.rows).toHaveLength(8);
    expect(state.rows[0].withdrawal.value).toBe("");
    expect(new Set(state.rows.map((r) => r.id)).size).toBe(8);
  });

  it("finds tampered rows via live balance check", () => {
    const { mismatched } = checkBalances(state);
    expect([...mismatched]).toEqual([state.rows[5].id, state.rows[6].id]);
  });

  it("clears mismatch after the user corrects the balance", () => {
    state.rows[5].balance.value = "114861.41";
    expect(checkBalances(state).mismatched.size).toBe(0);
  });

  it("tracks open review items and acknowledgement", () => {
    expect(openReviewItems(state).map((o) => o.label)).toEqual(["Row 6", "Row 7"]);
    state.rows[5].acknowledged = true;
    state.rows[6].acknowledged = true;
    expect(openReviewItems(state)).toHaveLength(0);
  });

  it("validates edits", () => {
    expect(validationErrors(state)).toEqual([]);
    state.header.account_number_masked.value = "123456781234";
    state.rows[0].deposit.value = "12,abc";
    state.rows[1].withdrawal.value = "5.00";
    const errs = validationErrors(state).join(" | ");
    expect(errs).toMatch(/at most 4 digits/);
    expect(errs).toMatch(/Row 1 deposit/);
    expect(errs).toMatch(/Row 2 Row has both/);
  });

  it("requires a date on added rows", () => {
    state.rows.push(emptyRow());
    expect(validationErrors(state).join()).toMatch(/Row 9 date: required/);
  });

  it("builds a clean save payload", () => {
    state.rows[0].deposit.value = "55,000.00";
    state.rows[0].reference.value = "  ";
    const p = buildSavePayload(state, " checked ");
    expect(p.file_name).toBe(fixture.file_name);
    expect(p.header.opening_balance).toBe("25000.00");
    expect(p.transactions[0].deposit).toBe("55000.00");
    expect(p.transactions[0].reference).toBeNull();
    expect(p.transactions[0].withdrawal).toBeNull();
    expect(p.reviewer_note).toBe("checked");
  });
});
