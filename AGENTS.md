# Contributor guide

## Project purpose

This service automatically acknowledges new buyer questions in Allegro Messages and buyer messages in Allegro issues/discussions. It is intentionally conservative: it sends only configured acknowledgement templates and never makes claim, refund, or fulfilment decisions.

## Architecture

- `app/main.py` contains the FastAPI application, dashboard, API routes, and polling orchestration.
- `app/allegro.py` is the only module that talks to Allegro HTTP APIs.
- `app/rules.py` contains the pure reply-decision rules.
- `app/store.py` persists settings, OAuth tokens, and idempotency keys in SQLite.
- `app/config.py` validates non-secret settings and supplies environment-based defaults.
- `util/test_auth.py` is a manual authentication smoke test.

Keep API integrations, business rules, persistence, and HTTP/UI handling separate when adding features.

## OAuth and secrets

- Use Allegro user authorization (Device Flow) for seller messages, issues, and orders. Client Credentials does not grant the required seller-user access.
- Never log, return, commit, or render access tokens, refresh tokens, client secrets, or `APP_ADMIN_TOKEN`.
- Allegro rotates refresh tokens. Persist a replacement refresh token atomically before making any later API request.
- Do not run more than one poller/replica against the same account and SQLite database; it can race reply sends and refresh-token rotation.
- Keep `ALLEGRO_CLIENT_ID`, `ALLEGRO_CLIENT_SECRET`, and `APP_ADMIN_TOKEN` only in local `.env` or Railway variables.

## Persistence and Railway

- The live configuration and OAuth state live in SQLite, not `.env`.
- Railway must mount a persistent Volume and set `DATA_DIR=/data`; container filesystem state is disposable.
- Do not expose unprotected write/configuration endpoints. `APP_ADMIN_TOKEN` protects these APIs using `Authorization: Bearer <token>`.
- The dashboard itself can be reached through a tunnel, but a tunnel is not a replacement for API authentication if a public Railway domain exists.

## Allegro API behavior

- Existing buyer threads: `/messaging/threads` and `/messaging/threads/{id}/messages` with `application/vnd.allegro.public.v1+json`.
- Issues/claims: `/sale/issues` and `/sale/issues/{id}/chat` with `application/vnd.allegro.beta.v1+json`.
- A purchase can be detected through `/order/events`, but Allegro does not offer a general endpoint to open a new buyer message solely because an order was placed. Do not promise or implement that behaviour without confirming a supported API path.
- Before changing Allegro paths, media types, authentication, or issue behavior, check the current official Allegro developer docs; these endpoints are evolving.

## Reply safety

- Preserve durable idempotency keys. Do not mark a reply complete before Allegro accepts it; release the key after a failed send so it can retry.
- Preserve the ten-minute age guard unless the product owner explicitly changes it. It prevents historic threads from receiving replies after deployment.
- Keep automatic issue replies limited to `REGULAR` acknowledgements. Never automatically accept/reject claims, request returns, issue refunds, or change claim status.
- Validate settings before saving. Keep template content and polling settings configurable through the dashboard.

## Local workflow

Use `uv`; do not add a parallel dependency-management approach.

```bash
uv sync
uv run ruff check .
uv run pyright
uv run uvicorn app.main:app --reload --port 8000
```

Run both Ruff and Pyright after Python changes. For changes to routes or the dashboard, also make a local request to `/health`, `/`, and the affected authenticated endpoint. Do not make live Allegro calls in automated tests.

## Working tree etiquette

- The repository may contain user changes. Preserve unrelated modifications.
- Use `apply_patch` for edits.
- Do not commit, deploy, rotate credentials, or make external Allegro changes unless explicitly requested.
