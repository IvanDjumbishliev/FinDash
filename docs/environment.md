# Environment reference

Django reads process environment variables first, then `backend/.env`. Compose uses the file selected by `--env-file` to interpolate the development stack. Use `.env.example` to create a separate `.env.compose`. Vite reads `VITE_*` settings in its own environment or `frontend/.env`. Vite values can be included in browser bundles, so keep credentials in the backend or your deployment secret store.

## Django and database

| Variable | Purpose |
| --- | --- |
| `DJANGO_ENV` | `development` by default. `production` disables debug and development API docs and requires a strong key, trusted hosts, PostgreSQL, and a broker. |
| `DJANGO_SECRET_KEY` | Secret for Django signing and JWTs. Required for Compose and production. Share it across app processes. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames. Local defaults are localhost and loopback addresses. Production requires explicit hosts. |
| `DJANGO_CORS_ALLOWED_ORIGINS` | Comma-separated exact origins with scheme and port. Local defaults allow Vite on port 5173. Production defaults to an empty list. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Exact origins trusted for cookie-authenticated writes. The default list is empty. |
| `DJANGO_TRUST_PROXY_HEADERS` | Enables trust in the HTTPS header from a private proxy. Defaults to false. |
| `DJANGO_HSTS_SECONDS` | Production HTTPS policy duration in seconds. Defaults to 31536000. |
| `DJANGO_HSTS_INCLUDE_SUBDOMAINS`, `DJANGO_HSTS_PRELOAD` | Optional production HSTS policies. Both default to false. |
| `DJANGO_THROTTLE_CACHE_URL` | Private Redis URL for shared rate limits. Omit for process-local throttling. |
| `DJANGO_THROTTLE_NUM_PROXIES` | Defaults to 0. Set to 1 only with a private backend and a trusted edge that replaces forwarding headers. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection settings. Port defaults to 5432. Without a database name, development uses SQLite. |
| `DB_SSLMODE`, `DB_SSLROOTCERT` | PostgreSQL TLS mode and optional CA file. Production defaults to `verify-full`. |
| `SQLITE_PATH` | Alternate local SQLite file. The default is `backend/db.sqlite3`. |
| `DJANGO_BUILD_STATIC` | Image-build switch that enables fingerprinted static collection without production secrets. |

## Integrations, jobs and containers

| Variable | Purpose |
| --- | --- |
| `API_KEY` | Optional server-side Gemini credential. An empty value disables provider calls. |
| `COPILOT_GEMINI_MODEL`, `BUDGET_GEMINI_MODEL`, `STATEMENT_GEMINI_MODEL`, `RECEIPT_GEMINI_MODEL` | Gemini model overrides. Their defaults are defined in Django settings. |
| `GROCERY_CATALOG_RETAILERS` | Comma-separated retailer IDs for catalog refresh. An empty list keeps retailer refreshes opt-in. |
| `CELERY_BROKER_URL` | Redis task broker. Local default is `redis://127.0.0.1:6379/0`. Production requires an explicit URL. |
| `NOTIFICATION_RETENTION_DAYS` | Inbox retention in days. Defaults to 90. |
| `NOTIFICATION_MARKET_CHECKS_ENABLED` | Opt-in scheduled market threshold checks. Defaults to false. |
| `NOTIFICATION_RENEWAL_INTERVAL_SECONDS`, `NOTIFICATION_BUDGET_INTERVAL_SECONDS` | Beat schedules. Defaults are 3600 and 900 seconds. |
| `NOTIFICATION_RETENTION_INTERVAL_SECONDS`, `NOTIFICATION_MARKET_INTERVAL_SECONDS` | Cleanup and optional stock checks. Defaults are 86400 and 900 seconds. |
| `NOTIFICATION_GROCERY_INTERVAL_SECONDS` | Periodic in-app deal evaluation interval. Defaults to 900 seconds. |
| `WARRANTY_PROOF_RETENTION_DAYS`, `WARRANTY_RECORD_RETENTION_DAYS` | Days to retain proof images and records after expiration. Defaults are 365 and 0. Set either to 0 to keep that data until deletion. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Compose database initialization. The database and user default to `findash`. Generate a password. |
| `BACKEND_PORT`, `FRONTEND_PORT` | Compose loopback ports. Defaults are 8000 and 5173. |
| `VITE_DEV_PROXY_TARGET` | Vite’s upstream during development. Defaults to `http://127.0.0.1:8000`. |
| `VITE_API_URL` | Public API origin at frontend build or dev time. The default uses the browser origin. |
| `FINDASH_BACKEND_UPSTREAM`, `FINDASH_DNS_RESOLVER` | Production Nginx upstream and resolver. Docker defaults are `backend:8000` and `127.0.0.11`. |
| `FIREFOX_BIN`, `GECKODRIVER_BIN` | Optional binary paths for the browser test harness. |

See [Compose setup and production requirements](../README.md#docker-compose-development) and the [example environment file](../.env.example).
