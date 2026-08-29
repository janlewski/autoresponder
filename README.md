# Allegro Autoresponder

A small FastAPI service that replies to new buyer questions and buyer issue messages, and sends one transaction-linked acknowledgement for each newly detected purchase. Its dashboard edits the persisted templates and polling options.

## What Allegro supports

- `GET /messaging/threads` and `POST /messaging/threads/{id}/messages` handle replies in **existing** buyer/seller threads.
- `GET /order/events` detects newly paid/ready orders. For each `READY_FOR_PROCESSING` event, the service uses `POST /messaging/messages` to send an acknowledgement linked to that order and buyer. The first poll creates a cursor only, so historic orders do not receive a message.
- `GET /sale/issues`, `GET /sale/issues/{id}/chat`, and `POST /sale/issues/{id}/message` support discussions and claims. The service only sends a `REGULAR` acknowledgement; it does not make legal/financial claim decisions.

Read the official guides: [Messages](https://developer.allegro.pl/tutorials/jak-zarzadzac-centrum-wiadomosci-XxWm2K890Fk), [issues and claims](https://developer.allegro.pl/tutorials/jak-zarzadzac-dyskusjami-E7Zj6gK7ysE), and [orders/events](https://developer.allegro.pl/tutorials/jak-obslugiwac-zamowienia-GRaj0qyvwtR).

The connected account needs `allegro:api:messaging` and `allegro:api:orders:read` scopes. The order acknowledgement is sent when Allegro reports `READY_FOR_PROCESSING`: payment is complete, or the buyer selected cash-on-delivery/pickup.

## Authentication

Create a REST API app at [Allegro Developer Apps](https://apps.developer.allegro.pl/) and configure its Client ID and Client Secret as Railway variables:

```text
ALLEGRO_CLIENT_ID=...
ALLEGRO_CLIENT_SECRET=...
APP_ADMIN_TOKEN=a-long-random-secret
DATA_DIR=/data
DEBUG_READ_ONLY=false
```

`APP_ADMIN_TOKEN` protects the settings and OAuth endpoints; it is deliberately not stored in the database. `DATA_DIR` must be a Railway Volume mount, for example `/data`. Without a volume, a deploy discards the configuration and eventually breaks authorization.

Set `DEBUG_READ_ONLY=true` to enable read-only debug mode on first run. As with the other non-secret settings, once configuration has been saved through the dashboard, the persisted SQLite value takes precedence over this environment default.

Open the dashboard and use **Connect Allegro**. It uses Allegro Device Flow, so it works through an SSH tunnel and requires no public redirect URL. Allegro gives an access token valid for 12 hours and rotates the refresh token on every refresh (with a short 60-second overlap). The app saves the replacement refresh token in SQLite before it makes another request; do not run two replicas against the same Allegro account/database.

To access a private Railway service, forward its HTTP port with the Railway CLI/SSH method you normally use, then open the forwarded localhost URL. Enter `APP_ADMIN_TOKEN` when prompted by the dashboard. Do not rely on the tunnel alone if the service also has a public domain.

## Run locally

```bash
uv sync
export ALLEGRO_CLIENT_ID=...
export ALLEGRO_CLIENT_SECRET=...
export APP_ADMIN_TOKEN=local-secret
uv run uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000`. Local state is saved in `.data/autoresponder.sqlite3`; it is ignored by Git. Set `ALLEGRO_ENV=sandbox` to test against Allegro Sandbox.

## Design notes

- The polling worker re-reads saved settings between polls.
- Enable **read-only debug mode** in the dashboard to inspect the messages, issues, and purchase events fetched during the current process. While enabled, it sends no acknowledgements and does not advance the order-event cursor.
- Reply keys are durable, so restarts do not send the same acknowledgement twice. A failed send releases its key for retry.
- Keep polling at one worker/replica. Multiple workers can race both outgoing replies and the single-use refresh-token rotation.
- By default, messages older than ten minutes are ignored to avoid responding to historic conversations after first deployment.
