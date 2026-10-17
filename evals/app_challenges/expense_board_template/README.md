# Expense Board Challenge

Build a small single-page expense board in this workspace.

Use this repo as the product surface:
- `index.html`
- `styles.css`
- `app.js`

Requirements:
- Render a form to add expenses with:
  - `label`
  - `category`
  - `amount`
- Each expense tracks a reimbursement state: `outstanding` or `reimbursed`.
- Support filtering by category and status (`all`, `outstanding`, `reimbursed`).
- Show summary values:
  - total expenses
  - total amount
  - outstanding amount
- Persist expenses in storage under `expense-board:v1`.
- Add an export button that renders a JSON summary into the page.
- Show a helpful empty state when there are no matching expenses.

Implementation notes:
- `app.js` should export `STORAGE_KEY` and `bootstrapExpenseBoard(options = {})`.
- `bootstrapExpenseBoard` should accept:
  - `document`
  - `storage`
  - `now`
- The browser entrypoint should still auto-bootstrap on `DOMContentLoaded`.

Done condition:
- `npm test -- --run` passes.

