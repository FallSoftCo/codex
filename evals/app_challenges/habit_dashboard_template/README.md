# Habit Dashboard Challenge

Build a small single-page web app in this workspace.

The app should help a user track daily habits and must satisfy the automated test suite.

Use this repo as the product surface:
- `index.html`
- `styles.css`
- `app.js`

Requirements:
- Render a habit dashboard with a form to add habits.
- Each habit has:
  - `name`
  - `category`
  - `targetDays`
  - completion state for "today"
- Support filtering by category and by status (`all`, `completed`, `pending`).
- Show summary values:
  - total habits
  - completed today
  - completion rate
- Persist habits in storage under `habit-dashboard:v1`.
- Add an export button that renders a JSON summary into the page.
- Show a friendly empty state when there are no matching habits.

Implementation notes:
- `app.js` should export `STORAGE_KEY` and `bootstrapHabitDashboard(options = {})`.
- `bootstrapHabitDashboard` should accept:
  - `document`
  - `storage`
  - `now`
- `now()` should return a stable date string like `2026-04-23`.
- The browser entrypoint should still auto-bootstrap on `DOMContentLoaded`.

Done condition:
- `npm test -- --run` passes.

