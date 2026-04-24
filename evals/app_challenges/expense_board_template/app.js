export const STORAGE_KEY = "expense-board:v1";

function defaultNow() {
  return new Date().toISOString().slice(0, 10);
}

function readExpenses(storage) {
  const raw = storage.getItem(STORAGE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function formatCurrency(value) {
  return `$${Number(value || 0).toFixed(2)}`;
}

export function bootstrapExpenseBoard(options = {}) {
  const doc = options.document ?? document;
  const storage = options.storage ?? window.localStorage;
  const now = options.now ?? defaultNow;

  const summaryTotal = doc.querySelector("#summaryTotal");
  const summaryAmount = doc.querySelector("#summaryAmount");
  const summaryOutstanding = doc.querySelector("#summaryOutstanding");
  const emptyState = doc.querySelector("#emptyState");
  const exportOutput = doc.querySelector("#exportOutput");

  const expenses = readExpenses(storage);
  const totalAmount = expenses.reduce(
    (sum, expense) => sum + Number.parseFloat(expense.amount ?? 0),
    0
  );

  if (summaryTotal) {
    summaryTotal.textContent = String(expenses.length);
  }
  if (summaryAmount) {
    summaryAmount.textContent = formatCurrency(totalAmount);
  }
  if (summaryOutstanding) {
    summaryOutstanding.textContent = formatCurrency(totalAmount);
  }
  if (emptyState) {
    emptyState.hidden = expenses.length > 0;
  }
  if (exportOutput) {
    exportOutput.textContent = JSON.stringify(
      {
        generatedForDate: now(),
        totalExpenses: expenses.length,
        totalAmount,
        outstandingAmount: totalAmount,
        expenses
      },
      null,
      2
    );
  }

  return { expenses };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      bootstrapExpenseBoard();
    });
  } else {
    bootstrapExpenseBoard();
  }
}

