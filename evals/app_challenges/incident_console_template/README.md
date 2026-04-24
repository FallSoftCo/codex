# Incident Console Challenge

Build a small single-page incident console in this workspace.

Use this repo as the product surface:
- `index.html`
- `styles.css`
- `app.js`

Requirements:
- Render a form to add incidents with:
  - `title`
  - `severity`
  - `owner`
- Each incident tracks a status for today: `open` or `resolved`.
- Support filtering by severity and status (`all`, `open`, `resolved`).
- Show summary values:
  - total incidents
  - open incidents
  - high severity open incidents
- Persist incidents in storage under `incident-console:v1`.
- Add an export button that renders a JSON summary into the page.
- Show a helpful empty state when there are no matching incidents.

Implementation notes:
- `app.js` should export `STORAGE_KEY` and `bootstrapIncidentConsole(options = {})`.
- `bootstrapIncidentConsole` should accept:
  - `document`
  - `storage`
  - `now`
- The browser entrypoint should still auto-bootstrap on `DOMContentLoaded`.

Done condition:
- `npm test -- --run` passes.

