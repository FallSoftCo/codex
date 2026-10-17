export const STORAGE_KEY = "incident-console:v1";

function defaultNow() {
  return new Date().toISOString().slice(0, 10);
}

function readIncidents(storage) {
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

export function bootstrapIncidentConsole(options = {}) {
  const doc = options.document ?? document;
  const storage = options.storage ?? window.localStorage;
  const now = options.now ?? defaultNow;

  const summaryTotal = doc.querySelector("#summaryTotal");
  const summaryOpen = doc.querySelector("#summaryOpen");
  const summaryHighOpen = doc.querySelector("#summaryHighOpen");
  const emptyState = doc.querySelector("#emptyState");
  const exportOutput = doc.querySelector("#exportOutput");

  const incidents = readIncidents(storage);

  if (summaryTotal) {
    summaryTotal.textContent = String(incidents.length);
  }
  if (summaryOpen) {
    summaryOpen.textContent = String(incidents.length);
  }
  if (summaryHighOpen) {
    summaryHighOpen.textContent = "0";
  }
  if (emptyState) {
    emptyState.hidden = incidents.length > 0;
  }
  if (exportOutput) {
    exportOutput.textContent = JSON.stringify(
      {
        generatedForDate: now(),
        totalIncidents: incidents.length,
        openIncidents: incidents.length,
        highSeverityOpen: 0,
        incidents
      },
      null,
      2
    );
  }

  return { incidents };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      bootstrapIncidentConsole();
    });
  } else {
    bootstrapIncidentConsole();
  }
}

