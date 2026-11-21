# FinDash

**A personal finance command center powered by an AI advisor.**

FinDash brings transactions, expense insights, document imports, shopping deals, and stock watchlists into one focused dashboard.

## Highlights

- Interactive expense overview with category breakdowns
- Manual transaction entry and recent activity tracking
- Bank statement PDF import
- AI-powered financial chat and personalized summaries
- Lidl and Kaufland deal discovery
- Stock search and watchlist management
- JWT authentication with protected routes

## Tech stack

| Frontend | Backend |
| --- | --- |
| React 19, Vite | Django, Django REST Framework |
| React Router | Simple JWT |
| Chart.js, Recharts | SQLite locally / PostgreSQL in production |
| Axios | Google GenAI integration |

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The backend runs at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173`.

Create `frontend/.env` to override the API origin:

```env
VITE_API_URL=http://localhost:8000
```

Create `backend/.env` for optional integrations:

```env
API_KEY=your_google_genai_key

# Optional PostgreSQL configuration
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=
```

Without database environment variables, Django automatically uses SQLite.

### Live store deals

The Deals page reads the public Kaufland, Lidl, and Fantastico offers. The backend
needs HTTPS access to the retailer sites and their brochure hosts. It uses Lidl’s
current offers and product photos, and reads the text and images published by
the active Фантастико brochure viewer.


## Useful commands

```bash
# Frontend
cd frontend
npm run dev
npm run build
npm run lint

# Backend
cd backend
python manage.py check
python manage.py test
python manage.py migrate
```

## Project structure

```text
frontend/
  src/
    components/   Reusable dashboard and UI components
    pages/        Application routes
    styles/       Global and feature styles
backend/
  api/            REST views, models, serializers, integrations
  backend/        Django settings and root routing
```

## API

Major endpoints are served below `/api/`:

- `POST /api/user/register/`
- `POST /api/token/` and `POST /api/token/refresh/`
- `GET|POST /api/transactions/`
- `GET /api/transaction-stats/`
- `POST /api/bank-statement/`
- `GET /api/summary/`
- `POST /api/chat/`
- `GET|POST /api/stocks/watchlist/`

### Financial Copilot

The **Financial Copilot** page uses the existing account and transaction ledger.
Check the consent box to allow Gemini to process your question and limited
conversation context for this session. **Privacy settings** can disable Gemini
sharing entirely, enable saved history, or delete the saved conversation.
History is off by default. Turning it off deletes the saved conversation.
FinDash retains up to 24 turns for the account when history is enabled and uses
the latest four for follow-ups. With history off, the tab keeps a signed,
account-bound context token that expires an hour after issuance.

- `POST /api/chat/` accepts JSON such as
  `{"prompt":"How much did I spend on groceries last month?","consent":true}`.
  Include the previous `context_token` on follow-ups when history is off.
  A successful `201` returns `answer`, `metrics`, inclusive `date_ranges`,
  optional `visualization` metadata, and `context_token` (null when history is saved).
- `GET|PATCH /api/chat/settings/` reads or updates the boolean fields
  `sharing_enabled` and `history_enabled`. Sharing is available by default,
  with explicit consent still required for each request.
- `GET|DELETE /api/chat/history/` reads or clears the authenticated user's
  saved turns. Deleting also invalidates previous context tokens.
- Chat errors include a code and a user-facing message. Refresh the conversation
  after a `409` stale context response. Timeouts and transient transport or server
  failures allow one automatic retry. Gemini rate limits are returned as `429`.

Gemini selects read-only tools using the current question and up to four prior
questions with inferred date ranges. FinDash calculates amounts and writes
answers locally. The provider receives no tool results, merchant names,
transaction descriptions, or uploaded statements from the ledger. Questions
can contain information the user types. Spending calculations use the account
timezone, keep currencies separate, exclude identified internal transfers,
and deduct recognized refunds. Subscription costs are estimates. Each
date range can span up to 366 days, and recent transactions are capped at 20 rows.
Set `COPILOT_GEMINI_MODEL` to override the server's default model.

`GET /api/summary/` computes dashboard insights locally, using the last 30 days
by default. An optional `from-date=YYYY-MM-DD` can cover up to 366 days through today.

### Spending heatmap

`GET /api/analytics/spending-heatmap/?start=2026-01-01&end=2026-01-31&currency=EUR`
returns the inclusive local date range in ascending order. Supply dates as `YYYY-MM-DD`.
When omitted, `end` defaults to today in the account timezone, and `start` defaults to
365 days before `end`. A range may include at most 366 dates. The optional currency
filter defaults to the profile currency or USD for accounts without a profile.

The response contains `start`, `end`, `timezone`, `currency`, and a `days` array.
Each day contains `date`, `total_spending`, `transaction_count`, and `category_totals`
(an object keyed by category), plus `category_counts` for category filtering.
Money amounts are decimal strings. Empty dates have
`"0.00"` spending, a count of zero, and an empty category object. The count includes
purchases and recognized refunds. Refunds reduce spending on the day they post, so
net spending can be negative. Income and recognized internal transfers are excluded.

`GET /api/analytics/spending-heatmap/day/?date=2026-01-15&currency=EUR&category=groceries`
returns the authenticated user's contributing transactions for one local date.
Currency and category are optional. The detail list uses the same spending and refund
rules as the calendar.

The dashboard uses four positive-spending bands, ending at 25%, 50%, 75%, and 100%
of the highest daily net spend for the selected year and category. The legend gives
the exact currency bounds. Days with purchases or refunds whose net is zero or
negative use a striped cell. Empty days use a neutral cell. The scale recalculates
when the year or category changes, so use the legend when comparing views.

Use `GET /api/user/profile/timezone/` to read the account timezone and
`PATCH /api/user/profile/timezone/` with `{"timezone":"Europe/Sofia"}` to update it.
Accounts default to UTC. Both endpoints require authentication.

### Bank statement imports

From the dashboard, select **Upload statement**. The wizard walks through **Upload**, **Parse**, **Review**, **Confirm**, and **Complete**. Drop a PDF or CSV onto the uploader or use its file picker. Review edits and approvals, check expected imported and skipped counts, then confirm to save. The completion receipt shows the result and refreshes dashboard spending and recent activity. Files are limited to 10 MiB and 2,000 rows. CSV is parsed locally, with automatic mapping for common English and Bulgarian headers. You can override the mapping, choose day-first or month-first dates, and enter a default currency. The default category is `general` when the statement supplies none.

- `POST /api/bank-statement/preview/` accepts multipart `file`, optional `mapping` (a JSON object mapping transaction fields to header names), `date_order` (`DMY` or `MDY`), `default_currency`, and `allow_external_processing` (`true` for this PDF only). It returns an owner-scoped import ID, status, and either normalized transactions, mapping information, or sanitized errors. No transactions are saved by this endpoint.
- `GET /api/bank-statement/imports/{id}/` returns the preview or final status. `DELETE` discards a pending import. `POST /api/bank-statement/imports/{id}/confirm/` saves all validated rows atomically. Retrying confirmation for the same ID does not add them again.
- The legacy `POST /api/bank-statement/` still commits compatible PDFs directly. Layouts the local parser cannot recognize require explicit consent and a configured Gemini key. Gemini receives the PDF inline with the request. FinDash creates no provider Files API upload.
- The original file is not retained by FinDash. Prepared transaction rows are cleared on confirmation, discard, or expiry. Previews expire after 30 minutes. Owner requests clear expired previews, and deployments can schedule `python manage.py expire_statement_previews` for cleanup during idle periods.

#### Transaction review and import history

- Preview rows show cleaned merchant names, category suggestions and confidence, and possible duplicates. Duplicate checks compare the transaction day, signed amount, currency, normalized merchant, and bank reference when available. Two different explicit references are treated as different transactions. A missing reference can still produce a possible match.
- Use `PATCH /api/bank-statement/imports/{id}/` with the current `revision` and `changes` keyed by `row_id` to correct merchant or category and approve or reject rows. Approving a flagged match requires `allow_duplicate: true` for that row. Confirmation saves approved rows in one transaction and rechecks for duplicates added since review.
- User rules match normalized merchant names and take precedence over built-in rules. Manage them at `/api/bank-statement/rules/` and `/api/bank-statement/rules/{id}/`. These endpoints are owner-scoped.
- Optional `allow_ai_categorization=true` on the preview sends cleaned merchant names for uncertain rows to Gemini. Suggestions must pass category validation and be approved in review. PDF parsing consent is separate.
- `GET /api/bank-statement/imports/` lists import batches and statuses. `GET /api/bank-statement/imports/{id}/transactions/` lists transactions linked to that import. Both endpoints support limit/offset pagination. Earlier imports retain their batch counts but have no linked rows because provenance was not stored at the time.

#### Browser workflow test

With the backend and frontend dependencies installed, run the statement wizard test from the repository root:

```bash
backend/.venv/bin/python frontend/tests/e2e/statement_wizard.py
```

The test requires Firefox and geckodriver on `PATH` or the `FIREFOX_BIN` and `GECKODRIVER_BIN` overrides. It starts local servers with a temporary database and synthetic statements. External AI processing is disabled in the test server.

### Monthly budgets

Budget endpoints require a JWT access token. Create a budget with `POST /api/budgets/`:

```json
{"period":"2026-02","category":"groceries","amount":"250.00","currency":"EUR","alert_thresholds":[50,80,100]}
```

- Use an existing transaction category or omit `category` for an overall budget. One active budget per category and month, plus one active overall budget per month, is allowed.
- Periods accept `YYYY-MM` or `YYYY-MM-01` and return the month's first date. `GET /api/budgets/` accepts an optional `period` query parameter.
- `GET|PATCH|DELETE /api/budgets/{id}/` reads, edits, or removes a budget. Set `archived` to `true` with PATCH to retain it in history while making room for a replacement.
- `GET /api/budgets/overview/?period=2026-02` returns active category budgets and a separate optional overall budget. The period defaults to the current month. `GET /api/budgets/history/` groups all saved budgets by month, including archived records.
- Responses include actual spending, remaining budget, percentage used, and reached thresholds. An empty threshold list disables threshold tracking. History reflects the current transaction records for each saved month.
- Progress uses the configured Django timezone and exact-currency transactions. Negative amounts count as spending. Recognizable refund credits reduce spending in their recorded month and category. Clearly labeled internal transfers are excluded. Transaction descriptions are used because the transaction model has no refund or transfer type.

### Budget recommendations

- `POST /api/budgets/recommendations/` accepts `period` and optional `use_gemini` (a JSON boolean, default `false`). It uses up to six completed months and requires at least three months of positive net spending for a category in one currency. It returns proposed amounts, statistics, explanations, and a review ID valid for 30 minutes.
- Gemini only receives category/currency labels, estimates, and aggregate statistics after opt-in for that request. The statistical explanation remains available on provider failure. The model can be overridden with `BUDGET_GEMINI_MODEL` in the process environment.
- `POST /api/budgets/recommendations/apply/` requires `review_id`, selected `categories`, and `confirmed: true`. It applies the selection as one transaction and consumes the review. If a selected budget changed after generation, the request returns `409` and applies nothing.

## License

See [LICENSE](LICENSE).
