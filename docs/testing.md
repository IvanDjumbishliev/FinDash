# Testing FinDash

Install the locked dependencies with `uv sync --locked` in `backend/` and `npm ci` in `frontend/` before running these commands.

## Backend

Run from `backend/`.

```sh
uv run --locked python manage.py check
uv run --locked python manage.py makemigrations --check --dry-run
uv run --locked python manage.py test
uv run --locked python manage.py test api.test_database_integrity api.test_security api.test_statement_imports
uv run --locked python manage.py spectacular --validate --fail-on-warn --file /tmp/findash-openapi.yaml
```

Django creates a disposable test database. For PostgreSQL parity with CI, use an isolated development server and set the `DB_*` values described in the [environment reference](environment.md). The configured role needs permission to create a test database. To choose SQLite for a run even when PostgreSQL appears in `backend/.env`, prefix the command with `DJANGO_ENV=development DB_NAME=`.

Backend coverage includes Decimal calculations for budgets, scenarios and portfolios, JWT refresh and ownership, statement files and atomic imports, mocked Gemini responses, mocked background tasks, and database constraints that reject inconsistent writes.

## Frontend

Run from `frontend/`.

```sh
npm run lint
npm test
npm run build
node --test tests/budgets.test.js
```

Node tests handle form validation, error-message formatting, state transitions and chart data. Component checks render React markup and exercise component callbacks using the tooling already installed with Vite. Browser tests cover interactions that require the DOM.

## Browser workflows

Install Firefox and geckodriver and put them on `PATH`. You can set `FIREFOX_BIN` and `GECKODRIVER_BIN` when using a custom installation. Run from the repository root.

```sh
# Login, transaction creation, budget management, statement import and grocery optimization
backend/.venv/bin/python frontend/tests/e2e/run_suite.py

# All browser workflows, including Copilot, reports and notifications
backend/.venv/bin/python frontend/tests/e2e/run_suite.py --all

# Selected workflows
backend/.venv/bin/python frontend/tests/e2e/run_suite.py finance_workflow statement_wizard
```

The harness starts isolated Django, Vite and WebDriver processes for each scenario. It migrates a temporary SQLite database, disables live Gemini by default and uses synthetic statements and catalog data. Provider-specific scenarios inject stub responses. Failed scenarios print recent service logs and the runner reports all failures before exiting with a nonzero status.

## Coverage boundaries

GitHub Actions runs PostgreSQL checks, migrations, backend tests, OpenAPI validation, frontend lint, Node tests and the build. Run the browser suite separately for UI changes. The automation exercises Firefox and selected narrow layouts. Other browsers, live provider responses, production network policies, sustained traffic, and real bank documents need separate validation. The project does not collect line-coverage percentages or enforce a percentage threshold.
