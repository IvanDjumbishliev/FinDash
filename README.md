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

### Virtual portfolios

Open **Simulator** from navigation, or choose **Simulate trade** on a watchlist
card to prefill its ticker. All portfolio endpoints require authentication. Each portfolio is virtual
and belongs to its creator. Use the existing `GET /api/stocks/search/` to
look up tickers, then enter a simulated execution price for each trade.

- `GET|POST /api/portfolios/` lists or creates portfolios. Creation accepts
  `name` and an optional three-letter `currency` (default USD).
- `POST /api/portfolios/{id}/trades/` records a simulated `buy` or `sell`
  with `ticker`, `quantity`, `price`, optional `fees` (default zero), and
  optional `currency` (defaults to and must match the portfolio currency).
  The server records the timestamp. Fractional shares are supported.
  A sale cannot exceed the virtual units held. An optional UUID
  `client_order_id` makes identical retries return the existing trade and
  rejects changes to the original order terms.
- `GET /api/portfolios/{id}/trades/?limit=15&offset=0` lists recorded trades, newest first.
- `GET /api/portfolios/{id}/holdings/` returns open holdings, cost basis,
  market quote timestamps, and unrealized P/L when valuation is available.
- `GET /api/portfolios/{id}/performance/` returns current position totals,
  realized and unrealized P/L, fees, and per-ticker ledger figures including
  closed positions. Its chart series contains cumulative realized P/L after each
  of the latest 100 trade events, calculated from the entire virtual ledger.

FIFO consumes buy lots in recorded ledger order. Buy fees increase each
lot's basis. A partial sale allocates basis proportionally to the shares
sold, rounded to 16 decimal places with half-even rounding. The residual
basis stays with the lot and is released on closure. Sell fees reduce
proceeds. The API returns financial amounts as decimal strings.

The dashboard's virtual balance is the market value of open positions.
Total invested is cumulative simulated buy outlay including buy fees.
Allocation uses market value when every open position can be valued and FIFO
cost basis when quotes are incomplete. The performance chart represents
realized P/L at trade events.

Market quotes are separate from user-entered execution prices. If a quote
is missing, older than seven days, or denominated in a different currency
or subunit, the holding's market value and unrealized P/L are unavailable.
Incomplete portfolio valuations identify the priced subtotal. Only up to
25 open tickers are quoted per snapshot. The simulator tracks positions and
P/L without brokerage connectivity, virtual cash accounting, short sales,
or FX conversion. Splits and dividends require a verified corporate-action
feed before they can be applied.

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

### Cash flow forecast

Open **Forecast** to compare recorded and projected weekly cash flow, switch
between horizons, and inspect upcoming recurring payments. Apply an optional
starting balance to change the trajectory from cumulative cash flow to an
estimated balance. Both chart panels offer accessible data tables.

`GET /api/forecast/cash-flow/?horizon=60&currency=EUR` returns the authenticated
account's daily estimates beginning tomorrow in its configured timezone.
Supported horizons are 30, 60, and 90 days, with 30 as the default. The
currency defaults to the account's configured currency, or USD. No FX
conversion is applied.

Supply an end-of-today balance with the `X-Starting-Balance` header to project
balances without putting the value into the URL. The optional `starting_balance`
query parameter is also accepted when the header is omitted. The forecast
does not derive an opening balance from transactions. Without a supplied
balance, balance fields are null and the forecast reports cash flow only.

- Scheduled estimates include active confirmed subscriptions and recurring
  deposits or charges detected from up to 1,096 days of recorded activity.
  Recognized internal transfers are excluded and refunds reduce expenses.
  Paused and canceled subscriptions are excluded, and recognized historical
  charges are kept out of the variable spending estimate.
- Variable cash flow uses up to 26 complete seven-day blocks ending yesterday.
  At least eight blocks and recorded activity in at least half are required.
  Known recurring charges are removed. The lowest and highest tenth of each
  component's weekly amounts, at least one observation per tail, are capped
  at the nearest retained value before averaging. The average is spread across
  the forecast days. Sparse history produces scheduled-only information.
- With at least 16 complete weeks, variable activity in eight or more, and
  variation in weekly net cash flow, the response may include an illustrative
  historical scenario range. This uses the 10th and 90th percentiles
  of 1,000 resamples of contiguous two-week blocks. Scheduled amounts stay fixed.
  These are not calibrated confidence intervals. Missing ledger activity,
  schedule changes, and unknown accounts can materially change outcomes.

The response includes historical totals and coverage, up to 13 weeks of recorded
chart values in `history.weeks`, scheduled series, daily projections, horizon
totals, assumptions, and limitations. When available, `uncertainty.days` contains
scenario bounds for each date using the same simulated paths as the final range.

#### What-if scenarios

Use **What-if scenarios** on the forecast page to compare the baseline against
a monthly income increase, a variable category cut, a new weekly or monthly
expense, an omitted confirmed subscription, a one-time purchase, or an
alternate starting balance. Day 1 means the first forecast day. Omitted
subscriptions continue to exist and are only excluded from the comparison.

`POST /api/forecast/cash-flow/scenarios/preview/` accepts `horizon`, `currency`,
optional baseline `starting_balance`, and a `changes` object. Supported changes
are `monthly_income` and `purchase` (each with `amount` and optional `day`),
`recurring_expense` (also accepts `frequency`), `spending_reduction` (with
`category` and integer `percent`), `remove_subscription_id`, and a hypothetical
`starting_balance`. The response includes both daily paths, ending differences,
and notes for changes that cannot be modeled. A category reduction applies to
positive estimated variable expenses and is capped at the daily variable amount.
A balance difference needs a baseline starting balance.

`GET|POST /api/forecast/cash-flow/scenarios/` lists or saves named assumptions.
Saving accepts `name`, `horizon`, `currency`, and `changes`. Loading reruns the
assumptions against current data. `DELETE /api/forecast/cash-flow/scenarios/{id}/`
deletes a saved scenario. Simulation writes no financial records. Scenario paths
are hypothetical estimates and do not include uncertainty bounds.

### Financial reports

Open **Reports** and select a month and optionally a three-letter currency.
The report contains recorded income, expenses net of recognized refunds, cash
flow, category changes, the largest recorded expenses, and budget performance.
Internal transfers are excluded. Month-to-date reports use the comparable days
of the previous month. Subscription estimates reflect active confirmed
subscriptions as of generation. Financial goal tracking is currently unavailable.

- `POST /api/reports/` accepts optional `month` (`YYYY-MM`), `currency`, and
  `ai_consent` (JSON boolean, default false). The default month uses the account
  timezone and the default currency uses the profile or USD. The response
  contains `report` and `export_token`.
- `POST /api/reports/pdf/` accepts that response unchanged and returns an
  attachment. The export token is account-bound and expires after one hour.
  Export reuses the preview and makes no Gemini request.
- Reports are generated on demand and kept only in the browser preview and in
  PDFs users download. **Clear preview** removes the current in-app preview.

Optional Gemini interpretation receives only qualitative trend signals and
category names after explicit consent. Copilot's sharing setting applies.
Gemini failures leave the deterministic report and PDF export available.
AI interpretation is for information only.

Set a private, stable `DJANGO_SECRET_KEY` in the environment or `backend/.env`
for deployments. Django uses a process-local random key when it is omitted,
so JWTs and export tokens expire on restart and do not work across workers.
Existing sessions using the former bundled key must sign in again.

### Grocery catalog normalization

The catalog reuses the existing Bulgarian deals adapters. It stores retailer
product and offer IDs where supplied, advertised prices and currencies, package
quantities in kg, liters, or items, unit prices, and observed source dates.
Equivalent units share a normalized product name, while pack size and count
remain part of an offer's identity. Missing or ambiguous values stay unset.
An advertised offer establishes no store-level stock guarantee.

Live catalog refresh is disabled by default. Configure
`GROCERY_CATALOG_RETAILERS` for the retailers whose published access rules and
applicable terms permit your deployment's use, then run
`python manage.py refresh_grocery_catalog lidl kaufland fantastico` with only
those retailers enabled. Refreshes are limited to one attempt per retailer
per hour. Empty or failed imports retain the last successful snapshot.

`GroceryOffer.objects.current()` uses only dated, priced offers seen in a
successful refresh within the past 48 hours. `.comparable()` also requires a
known package unit price and excludes known membership-only prices. Kaufland's
price-free image fallback is omitted from catalog imports. The Fantastico
adapter has no reliable per-offer dates or separate product image URLs.
Its brochure offers can be retained as source observations and are excluded
from current comparisons until reliable dates are available.

#### Grocery product matching

`api.services.grocery_matching.match_offers(left, right)` classifies two
catalog offers as identical, comparable, incompatible, or needing review.
Identity is inferred from the catalog brand, normalized title, and package
details. Category and variant rules cover common Bulgarian and English
grocery names. Unsupported or ambiguous terms stay unresolved. Fuzzy scores
measure title similarity and carry no probability of product equivalence.

`Match.comparable_prices` provides per-kg, per-liter, or per-item prices
when both prices are known in the same currency. Use
`GroceryOffer.objects.comparable()` for current offers. A pair match supplies
no retailer-wide or market-wide price ranking.

Catalog staff can resolve eligible uncertain pairs through
`review_match(left, right, reviewer=staff_user, decision="approve")` or
`decision="reject"`. Approval yields a comparable alternative. Decisions are
bound to the pair's reviewed product details. Missing measurements and hard
compatibility conflicts cannot be approved through this service.
Passing `ai_assist=True` optionally requests a Gemini suggestion for an
eligible unresolved pair. The provider sees catalog descriptions, and validated
suggestions are cached for 24 hours. AI suggestions leave the pair in review.

#### Grocery basket optimization

`POST /api/grocery/optimize/` accepts an authenticated JSON shopping list.
For example, `{"items":[{"name":"Rice","quantity":1300,"unit":"g"}],
"max_stores":2,"overhead_per_store":"1.50"}`. Each item accepts `name`,
`quantity`, optional `unit` (kg, g, l, ml, or item), `preferred_brand`, and
`allow_substitutions` (default true). A package unit in the name or a known
product family can supply the canonical unit (kg, l, or item) when it is omitted.
The requested quantity is the total needed in that unit. Use whole numbers for item counts, and
combine duplicate lines first.

Set `currency` to EUR (default) or BGN. `allow_multi_store` defaults to true
with a `max_stores` of three. Overhead defaults to zero and is charged once
per store used. With substitutions enabled, price takes priority and a
preferred brand breaks equal-price ties. With substitutions disabled,
the optimizer requires an exact name match, the preferred brand if
specified, and the package size if specified in the title.

The solver enumerates store combinations and finds the minimum-cost
whole-package combination for each line. It returns per-retailer plans,
the best plan across the allowed stores, and a partial plan if a complete
basket is unavailable. The multi-store option may choose one store when
that plan costs less. Incomplete plans include a matched-items subtotal
and have a null estimated total. Diagnostic counts cover related
observations from the last 30 days, and the first 15 excluded
offers per item are shown. The API returns 422 when the catalog or exact
comparison exceeds a processing limit.

Savings, when present, compare against the lowest estimated complete
single-retailer basket in the observed catalog with the same shopping
list, currency, and overhead. These are estimates from advertised offers
with limited coverage and unverified store-level stock.

#### Grocery basket page

Open **Grocery basket** to search current advertised offers, edit quantities
and substitutions, and limit the retailers used for comparison. Complete
plans show an estimated total. For partial plans, the checklist includes
only matched packages and separately shows missing items.

`GET /api/grocery/catalog/?q=milk&currency=EUR&retailers=lidl,kaufland`
returns up to 12 suggestions. `POST /api/grocery/optimize/` accepts an optional
`retailers` array. `GET|POST /api/grocery/lists/` lists or saves the current
account's named lists and comparison settings. `DELETE /api/grocery/lists/{id}/`
deletes a saved list. Saved lists hold inputs and can be optimized against
the current catalog each time they are loaded.

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
