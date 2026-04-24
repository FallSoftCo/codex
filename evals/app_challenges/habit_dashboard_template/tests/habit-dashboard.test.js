import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeEach, describe, expect, test } from "vitest";

import { STORAGE_KEY, bootstrapHabitDashboard } from "../app.js";

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
    },
    removeItem(key) {
      state.delete(key);
    },
    clear() {
      state.clear();
    }
  };
}

function seedHabit(overrides = {}) {
  return {
    id: overrides.id ?? crypto.randomUUID(),
    name: overrides.name ?? "Drink Water",
    category: overrides.category ?? "health",
    targetDays: overrides.targetDays ?? 5,
    completedDates: overrides.completedDates ?? [],
    createdAt: overrides.createdAt ?? "2026-04-21T10:00:00.000Z"
  };
}

function boot(seed = []) {
  document.open();
  document.write(HTML);
  document.close();
  const storage = createMemoryStorage(seed);
  bootstrapHabitDashboard({
    document,
    storage,
    now: () => "2026-04-23"
  });
  return { storage };
}

function text(id) {
  return document.querySelector(id)?.textContent?.trim() ?? "";
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

describe("habit dashboard challenge", () => {
  test("renders an empty state with zeroed summary values", () => {
    boot();

    expect(text("#summaryTotal")).toBe("0");
    expect(text("#summaryCompleted")).toBe("0");
    expect(text("#summaryRate")).toBe("0%");
    expect(document.querySelector("#emptyState")?.hidden).toBe(false);
  });

  test("adds habits, updates summary values, and persists them", () => {
    const { storage } = boot();

    document.querySelector("#habitName").value = "Read 20 pages";
    document.querySelector("#habitCategory").value = "learning";
    document.querySelector("#habitTarget").value = "4";
    submit(document.querySelector("#habitForm"));

    document.querySelector("#habitName").value = "Walk outside";
    document.querySelector("#habitCategory").value = "health";
    document.querySelector("#habitTarget").value = "6";
    submit(document.querySelector("#habitForm"));

    expect(document.querySelectorAll('[data-testid="habit-card"]').length).toBe(2);
    expect(text("#summaryTotal")).toBe("2");

    const stored = JSON.parse(storage.getItem(STORAGE_KEY));
    expect(stored).toHaveLength(2);
    expect(stored.map((habit) => habit.name)).toEqual([
      "Read 20 pages",
      "Walk outside"
    ]);
  });

  test("filters by category and completion status", () => {
    boot([
      seedHabit({ id: "a", name: "Jog", category: "health", completedDates: ["2026-04-23"] }),
      seedHabit({ id: "b", name: "Sketch", category: "creative" }),
      seedHabit({ id: "c", name: "Stretch", category: "health" })
    ]);

    document.querySelector("#filterCategory").value = "health";
    change(document.querySelector("#filterCategory"));

    expect(document.querySelectorAll('[data-testid="habit-card"]').length).toBe(2);

    document.querySelector("#filterStatus").value = "completed";
    change(document.querySelector("#filterStatus"));

    const cards = [...document.querySelectorAll('[data-testid="habit-card"]')];
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain("Jog");
  });

  test("toggles completion for today and persists the change", () => {
    const { storage } = boot([seedHabit({ id: "habit-1", completedDates: [] })]);

    click(document.querySelector('[data-action="toggle-complete"]'));

    expect(text("#summaryCompleted")).toBe("1");
    expect(text("#summaryRate")).toBe("100%");

    const stored = JSON.parse(storage.getItem(STORAGE_KEY));
    expect(stored[0].completedDates).toContain("2026-04-23");
  });

  test("exports a JSON summary for the current dashboard state", () => {
    boot([
      seedHabit({ id: "a", completedDates: ["2026-04-23"] }),
      seedHabit({ id: "b", category: "creative" })
    ]);

    click(document.querySelector("#exportButton"));

    const exportPayload = JSON.parse(text("#exportOutput"));
    expect(exportPayload.generatedForDate).toBe("2026-04-23");
    expect(exportPayload.totalHabits).toBe(2);
    expect(exportPayload.completedToday).toBe(1);
    expect(exportPayload.completionRate).toBe(50);
    expect(exportPayload.habits).toHaveLength(2);
  });
});

