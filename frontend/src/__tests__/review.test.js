import fixture from "./fixtures/extraction.json";
import {
  EMPTY_FILTERS,
  buildSavePayload,
  checkBalances,
  confidenceLevel,
  detectCategory,
  emptyRow,
  filterRows,
  formatAmount,
  formatRupees,
  hasFilters,
  openReviewItems,
  rowType,
  summarize,
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

describe("detectCategory", () => {
  it.each([
    ["Swiggy lunch order", "Food"],
    ["UPI/BIGBASKET GROCERIES", "Food"],
    ["IMPS/REFUND AMAZON", "Shopping"],
    ["SALARY CREDIT ACME PVT LTD", "Salary"],
    ["NEFT/RENT PAYMENT", "Bills"],
    ["ELECTRICITY BILL MSEDCL", "Bills"],
    ["Uber ride home", "Transport"],
    ["Netflix subscription", "Entertainment"],
    ["Apollo Pharmacy", "Health"],
    ["College tuition", "Education"],
    ["INTEREST CREDIT", "Other"],
    ["", "Other"],
    [null, "Other"],
  ])("%s -> %s", (description, expected) => {
    expect(detectCategory(description)).toBe(expected);
  });

  it("matches whole words only", () => {
    expect(detectCategory("Current account charges")).toBe("Other"); // not "rent"
    expect(detectCategory("Business loan")).toBe("Other"); // not "bus"
    expect(detectCategory("UPI-SWIGGY-9876@ybl")).toBe("Food");
    expect(detectCategory("zomato")).toBe("Food");
  });
});

describe("categories, filters and summary", () => {
  let state;
  beforeEach(() => {
    state = toReviewState(fixture);
  });
  const mk = (date, description, deposit, withdrawal, category = "Other") => {
    const r = emptyRow();
    r.date.value = date;
    r.description.value = description;
    r.deposit.value = deposit;
    r.withdrawal.value = withdrawal;
    r.category = category;
    return r;
  };
  const ids = (rows) => rows.map((r) => state.rows.indexOf(r) + 1); // 1-based row numbers

  it("gives every extracted row a category and saves it", () => {
    expect(state.rows.map((r) => r.category)).toEqual(["Salary", "Salary", "Other", "Bills", "Food", "Shopping", "Bills", "Other"]);
    expect(buildSavePayload(state).transactions[5].category).toBe("Shopping");
    expect(emptyRow().category).toBe("Other");
  });

  it("derives type from deposit / withdrawal", () => {
    expect(state.rows.map(rowType)).toEqual(["Income", "Income", "Expense", "Expense", "Expense", "Income", "Expense", "Income"]);
    expect(rowType(emptyRow())).toBe("");
  });

  it("returns everything when no filter is set", () => {
    expect(hasFilters(EMPTY_FILTERS)).toBe(false);
    expect(filterRows(state.rows, EMPTY_FILTERS)).toHaveLength(8);
  });

  it("searches descriptions: partial and case-insensitive", () => {
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, search: "amaz" }))).toEqual([6]);
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, search: " SALARY " }))).toEqual([1, 2]);
    expect(filterRows(state.rows, { ...EMPTY_FILTERS, search: "nothing like this" })).toEqual([]);
  });

  it("filters by date range, both ends included", () => {
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, from: "2026-09-05", to: "2026-09-08" }))).toEqual([3, 4, 5, 6]);
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, from: "2026-09-10" }))).toEqual([7, 8]);
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, to: "2026-09-03" }))).toEqual([1]);
  });

  it("filters by amount, both ends included", () => {
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, min: "15000" }))).toEqual([1, 2, 4]);
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, max: "977.47" }))).toEqual([6, 7, 8]);
    expect(filterRows(state.rows, { ...EMPTY_FILTERS, max: "abc" })).toHaveLength(8); // ignored
  });

  it("filters by type and category", () => {
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, type: "Expense" }))).toEqual([3, 4, 5, 7]);
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, type: "Income" }))).toEqual([1, 2, 6, 8]);
    expect(ids(filterRows(state.rows, { ...EMPTY_FILTERS, category: "Bills" }))).toEqual([4, 7]);
  });

  it("applies all filters together", () => {
    const f = { search: "upi", from: "2026-09-01", to: "2026-09-30", min: "100", max: "5000", type: "Expense", category: "Food" };
    expect(hasFilters(f)).toBe(true);
    expect(ids(filterRows(state.rows, f))).toEqual([5]);
    expect(filterRows(state.rows, { ...f, category: "Health" })).toEqual([]);
  });

  it("summarizes income, expenses, savings and the top expense category", () => {
    expect(summarize(state.rows)).toEqual({
      income: 110802.01,
      expenses: 21831.5,
      savings: 88970.51,
      topCategory: { name: "Bills", amount: 15977.47 },
    });
  });

  it("summary follows the filtered rows and handles edge cases", () => {
    const onlyFood = filterRows(state.rows, { ...EMPTY_FILTERS, category: "Food" });
    expect(summarize(onlyFood)).toMatchObject({ income: 0, expenses: 1936.77, savings: -1936.77 });
    expect(summarize([])).toEqual({ income: 0, expenses: 0, savings: 0, topCategory: null });
    expect(summarize([mk("2026-11-01", "a", "0.10", ""), mk("2026-11-01", "b", "0.20", "")]).income).toBe(0.3);
  });

  it("formats rupees with a sign for negative savings", () => {
    expect(formatRupees(88970.51)).toBe("₹88,970.51");
    expect(formatRupees(-7000)).toBe("-₹7,000.00");
    expect(formatRupees(0)).toBe("₹0.00");
  });
});
