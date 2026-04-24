export const STORAGE_KEY = "habit-dashboard:v1";

function defaultNow() {
  return new Date().toISOString().slice(0, 10);
}

function readHabits(storage) {
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

export function bootstrapHabitDashboard(options = {}) {
  const doc = options.document ?? document;
  const storage = options.storage ?? window.localStorage;
  const now = options.now ?? defaultNow;

  const summaryTotal = doc.querySelector("#summaryTotal");
  const summaryCompleted = doc.querySelector("#summaryCompleted");
  const summaryRate = doc.querySelector("#summaryRate");
  const emptyState = doc.querySelector("#emptyState");
  const exportOutput = doc.querySelector("#exportOutput");

  const habits = readHabits(storage);

  if (summaryTotal) {
    summaryTotal.textContent = String(habits.length);
  }
  if (summaryCompleted) {
    summaryCompleted.textContent = "0";
  }
  if (summaryRate) {
    summaryRate.textContent = "0%";
  }
  if (emptyState) {
    emptyState.hidden = habits.length > 0;
  }
  if (exportOutput) {
    exportOutput.textContent = JSON.stringify(
      {
        generatedForDate: now(),
        totalHabits: habits.length,
        completedToday: 0,
        completionRate: 0,
        habits
      },
      null,
      2
    );
  }

  return {
    habits
  };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      bootstrapHabitDashboard();
    });
  } else {
    bootstrapHabitDashboard();
  }
}

