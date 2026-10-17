import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeEach, describe, expect, test } from "vitest";

import { STORAGE_KEY, bootstrapIncidentConsole } from "../app.js";

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

function seedIncident(overrides = {}) {
  return {
    id: overrides.id ?? crypto.randomUUID(),
    title: overrides.title ?? "API outage",
    severity: overrides.severity ?? "high",
    owner: overrides.owner ?? "tony",
    status: overrides.status ?? "open",
    createdAt: overrides.createdAt ?? "2026-04-21T10:00:00.000Z"
  };
}

function boot(seed = []) {
  document.open();
  document.write(HTML);
  document.close();
  const storage = createMemoryStorage(seed);
  bootstrapIncidentConsole({
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

describe("incident console challenge", () => {
  test("renders an empty state with zeroed summary values", () => {
    boot();

    expect(text("#summaryTotal")).toBe("0");
    expect(text("#summaryOpen")).toBe("0");
    expect(text("#summaryHighOpen")).toBe("0");
    expect(document.querySelector("#emptyState")?.hidden).toBe(false);
  });

  test("adds incidents and persists them", () => {
    const { storage } = boot();

    document.querySelector("#incidentTitle").value = "Payment queue backlog";
    document.querySelector("#incidentSeverity").value = "high";
    document.querySelector("#incidentOwner").value = "chris";
    submit(document.querySelector("#incidentForm"));

    document.querySelector("#incidentTitle").value = "Missing favicon";
    document.querySelector("#incidentSeverity").value = "low";
    document.querySelector("#incidentOwner").value = "james";
    submit(document.querySelector("#incidentForm"));

    expect(document.querySelectorAll('[data-testid="incident-card"]').length).toBe(2);
    expect(text("#summaryTotal")).toBe("2");
    expect(text("#summaryOpen")).toBe("2");
    expect(text("#summaryHighOpen")).toBe("1");

    const stored = JSON.parse(storage.getItem(STORAGE_KEY));
    expect(stored).toHaveLength(2);
    expect(stored[0].title).toBe("Payment queue backlog");
  });

  test("filters by severity and status", () => {
    boot([
      seedIncident({ id: "a", title: "API outage", severity: "high", status: "open" }),
      seedIncident({ id: "b", title: "Slow reports", severity: "medium", status: "resolved" }),
      seedIncident({ id: "c", title: "Queue lag", severity: "high", status: "resolved" })
    ]);

    document.querySelector("#filterSeverity").value = "high";
    change(document.querySelector("#filterSeverity"));
    expect(document.querySelectorAll('[data-testid="incident-card"]').length).toBe(2);

    document.querySelector("#filterStatus").value = "resolved";
    change(document.querySelector("#filterStatus"));
    const cards = [...document.querySelectorAll('[data-testid="incident-card"]')];
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain("Queue lag");
  });

  test("toggles incident status and updates the summary", () => {
    const { storage } = boot([seedIncident({ id: "incident-1", severity: "high", status: "open" })]);

    click(document.querySelector('[data-action="toggle-status"]'));

    expect(text("#summaryOpen")).toBe("0");
    expect(text("#summaryHighOpen")).toBe("0");

    const stored = JSON.parse(storage.getItem(STORAGE_KEY));
    expect(stored[0].status).toBe("resolved");
  });

  test("exports a JSON summary", () => {
    boot([
      seedIncident({ id: "a", severity: "high", status: "open" }),
      seedIncident({ id: "b", severity: "low", status: "resolved" })
    ]);

    click(document.querySelector("#exportButton"));

    const payload = JSON.parse(text("#exportOutput"));
    expect(payload.generatedForDate).toBe("2026-04-23");
    expect(payload.totalIncidents).toBe(2);
    expect(payload.openIncidents).toBe(1);
    expect(payload.highSeverityOpen).toBe(1);
    expect(payload.incidents).toHaveLength(2);
  });
});

