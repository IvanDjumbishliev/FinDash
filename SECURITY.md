# FinDash security and deployment assumptions

## Authorization review

The default DRF permission is authenticated access. Registration, token exchange, health probes, and public retailer/news endpoints are explicitly public and return no private financial records.

| Resource | Server-side authorization |
| --- | --- |
| Transactions, summaries, statistics, heatmap, profile and timezone | Use the authenticated user's profile or filter by its user ID. Transaction deletion resolves the ID within that account. |
| Budgets, budget reviews and subscriptions | List, resolve, update and delete within the owner queryset. Detection and recommendations use the owner's ledger. |
| Statement preview, review, confirmation, history, imported transactions and merchant rules | Resolve import and rule IDs under the authenticated owner. Imported-transaction rows are also filtered by transaction owner. |
| Goals, ledger entries, projections and saved goal scenarios | Resolve the goal under its owner first. Child records belong to that goal. Simulation does not write ledger entries. |
| Forecasts and saved cash-flow scenarios | Use the authenticated account for calculations, scenario lookup, and referenced subscriptions. |
| Watchlists, portfolios, trades, performance and exports | Resolve portfolios under the authenticated owner before reading or writing holdings and trades. Live market prices are public reference data. |
| Grocery catalog, optimizer and saved shopping lists | Catalog offers are public retailer data. Resolve saved lists under their owner. |
| Reports, Copilot, and notifications | Generate reports from the authenticated account, bind export tokens and conversational context to that account, and resolve notification IDs and preferences under its owner. |

API responses carry `Cache-Control: no-store`. Reverse proxies and CDNs should preserve this header and avoid logging authorization, response content, request bodies, and query strings. Production Django request errors log a status code without exception text. Treat PostgreSQL, backups, Celery broker, and the shared rate-limit cache as private systems.

## Browser sessions and throttles

Access tokens expire after ten minutes. Refresh tokens rotate on successful exchange, and the previous token is blacklisted. Logout clears browser tokens and attempts to revoke the refresh token server-side. An already issued access token can remain valid until expiry. A scheduled Celery task removes expired outstanding tokens. Apply Django migrations before starting the hardened backend or worker so the Simple JWT blacklist tables exist.

Browser JWTs still use local storage for compatibility. JavaScript running on the app origin can read them. The production SPA Content Security Policy limits scripts and connections to the app origin and blocks framing. Keep unrelated apps and user-controlled HTML on separate origins. An HttpOnly refresh-cookie migration with explicit CSRF protection would further reduce token exposure. Use separate browser profiles for different users sharing a device.

Deploy behind the trusted TLS edge documented in the README. Keep CORS closed for same-origin deployments and set explicit origins for separate clients. Keep Django admin behind a restricted ingress. The default IP throttle uses the direct peer address. Set `DJANGO_THROTTLE_NUM_PROXIES=1` only when the edge replaces client-supplied forwarding headers with one verified client IP and the backend is private. Configure a private shared Redis cache using `DJANGO_THROTTLE_CACHE_URL` for multi-worker production. Without it, rate limits are per process. DRF throttling is an application safeguard and allows some burst leakage under concurrency. Ingress controls are needed for volumetric traffic.

## Files, AI, jobs and external requests

- Statement uploads accept one supported CSV or PDF with type checks and a 10 MiB file limit. PDFs and parsed content have page, row and text limits. Parsing never runs document scripts. The native PDF parser still shares the application process. Resource limits and a dedicated parsing worker would further reduce risk from hostile PDFs.
- Opt-in Gemini parsing may send the original PDF for that request. Other AI features use consent gates and send the data needed for their task. Copilot executes only validated, read-only tools using the authenticated server identity. Provider prose never supplies Copilot's financial totals. Structured provider output remains untrusted and is validated before display or import.
- Legacy leaflet searches use public retailer results with no AI-directed network requests. Fantastico brochure requests check HTTPS hostnames and reject redirects. Restrict outbound access to private and metadata networks at the infrastructure level.
- Celery accepts JSON and tasks use explicit entry points. Broker access remains a trust boundary. Use private Redis with authenticated TLS in production. Jobs log status and counts with sanitized exception messages.
- FinDash uses authenticated HTTP polling for notifications. There are no inbound WebSocket routes. JWTs are passed in authorization headers.

## Dependency review

`npm audit` checks the frontend lockfile. For Python, export the locked requirements with `uv export --locked --no-hashes --no-emit-project` and pass the export to `pip-audit`. Both audits reported zero known advisories for the updated lockfiles on 22 November 2026. These checks cover published dependency advisories. Runtime images and system packages require separate scans and routine rebuilds.
