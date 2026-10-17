import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeEach, describe, expect, test } from "vitest";

import { STORAGE_KEY, bootstrapExpenseBoard } from "../app.js";

const THIS_DIR = dirname(fileURLToPath(import.meta.url));
const HTML = readFileSync(resolve(THIS_DIR, "../index.html"), "utf8");

function createMemoryStorage(seed = []) {
  const state = new Map();
  if (seed.length > 0) {
    state.set(STORAGE_KEY, JSON.stringify(seed));
  }
  return {
    getItem(key) {
      return state.has(key) ? state.get(key) : null;
    },
    setItem(key, value) {
      state.set(key, String(value));
    }
  };
}

function seedExpense(overrides = {}) {
  return {
    id: overrides.id ?? crypto.randomUUID(),
    label: overrides.label ?? "Team lunch",
    category: overrides.category ?? "meals",
    amount: overrides.amount ?? 24.5,
    status: overrides.status ?? "outstanding",
    createdAt: overrides.createdAt ?? "2026-04-21T10:00:00.000Z"
  };
}

function boot(seed = []) {
  document.open();
  document.write(HTML);
  document.close();
  const storage = createMemoryStorage(seed);
  bootstrapExpenseBoard({
    document,
    storage,
    now: () => "2026-04-23"
  });
  return { storage };
}

function text(selector) {
  return document.querySelector(selector)?.textContent?.trim() ?? "";
}

function click(element) {
  element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

function change(element) {
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function submit(element) {
  element.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("expense board challenge", () => {
  test("renders an empty state with zeroed summary values", () => {
    boot();

    expect(text("#summaryTotal")).toBe("0");
    expect(text("#summaryAmount")).toBe("$0.00");
    expect(text("#summaryOutstanding")).toBe("$0.00");
    expect(document.querySelector("#emptyState")?.hidden).toBe(false);
  });

  test("adds expenses and persists them", () => {
    const { storage } = boot();

    document.querySelector("#expenseLabel").value = "Team lunch";
    document.querySelector("#expenseCategory").value = "meals";
    document.querySelector("#expenseAmount").value = "24.50";
    submit(document.querySelector("#expenseForm"));

    document.querySelector("#expenseLabel").value = "Taxi";
    document.querySelector("#expenseCategory").value = "travel";
    document.querySelector("#expenseAmount").value = "18.25";
    submit(document.querySelector("#expenseForm"));

    expect(document.querySelectorAll('[data-testid="expense-card"]').length).toBe(2);
    expect(text("#summaryTotal")).toBe("2");
    expect(text("#summaryAmount")).toBe("$42.75");
    expect(text("#summaryOutstanding")).toBe("$42.75");

    const stored = JSON.parse(storage.getItem(STORAGE_KEY));
    expect(stored).toHaveLength(2);
  });

  test("filters by category and status", () => {
    boot([
      seedExpense({ id: "a", category: "meals", status: "outstanding" }),
      seedExpense({ id: "b", category: "travel", status: "reimbursed" }),
      seedExpense({ id: "c", category: "meals", status: "reimbursed" })
    ]);

    document.querySelector("#filterCategory").value = "meals";
    change(document.querySelector("#filterCategory"));
    expect(document.querySelectorAll('[data-testid="expense-card"]').length).toBe(2);

    document.querySelector("#filterStatus").value = "reimbursed";
    change(document.querySelector("#filterStatus"));
    const cards = [...document.querySelectorAll('[data-testid="expense-card"]')];
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain("Team lunch");
  });

  test("toggles reimbursement status and updates summary", () => {
    const { storage } = boot([seedExpense({ id: "expense-1", amount: 24.5, status: "outstanding" })]);

    click(document.querySelector('[data-action="toggle-status"]'));

    expect(text("#summaryOutstanding")).toBe("$0.00");

    const stored = JSON.parse(storage.getItem(STORAGE_KEY));
    expect(stored[0].status).toBe("reimbursed");
  });

  test("exports a JSON summary", () => {
    boot([
      seedExpense({ id: "a", amount: 20, status: "outstanding" }),
      seedExpense({ id: "b", amount: 30.5, status: "reimbursed" })
    ]);

    click(document.querySelector("#exportButton"));

    const payload = JSON.parse(text("#exportOutput"));
    expect(payload.generatedForDate).toBe("2026-04-23");
    expect(payload.totalExpenses).toBe(2);
    expect(payload.totalAmount).toBe(50.5);
    expect(payload.outstandingAmount).toBe(20);
    expect(payload.expenses).toHaveLength(2);
  });
});
