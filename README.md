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

## License

See [LICENSE](LICENSE).
