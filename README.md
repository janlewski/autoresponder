# Allegro Autoresponder

A small FastAPI service that replies once to new buyer questions in Allegro Messages and to a buyer's first message in an Allegro discussion/claim. Its dashboard edits the persisted reply templates and polling options.

## What Allegro supports

- `GET /messaging/threads` and `POST /messaging/threads/{id}/messages` handle replies in **existing** buyer/seller threads. This API does not provide a general “send a new purchase thank-you message” endpoint, so a completed purchase alone cannot be turned into an automatic message.
- `GET /order/events` is the reliable cursor-based way to detect new purchases. It is useful for a later order workflow (fulfilment, internal notifications, shipping), but not for creating a message to the buyer.
- `GET /sale/issues`, `GET /sale/issues/{id}/chat`, and `POST /sale/issues/{id}/message` support discussions and claims. The service only sends a `REGULAR` acknowledgement; it does not make legal/financial claim decisions.

Read the official guides: [Messages](https://developer.allegro.pl/tutorials/jak-zarzadzac-centrum-wiadomosci-XxWm2K890Fk), [issues and claims](https://developer.allegro.pl/tutorials/jak-zarzadzac-dyskusjami-E7Zj6gK7ysE), and [orders/events](https://developer.allegro.pl/tutorials/jak-obslugiwac-zamowienia-GRaj0qyvwtR).

## Authentication

Create a REST API app at [Allegro Developer Apps](https://apps.developer.allegro.pl/) and configure its Client ID and Client Secret as Railway variables:

```text
ALLEGRO_CLIENT_ID=...
ALLEGRO_CLIENT_SECRET=...
APP_ADMIN_TOKEN=a-long-random-secret
DATA_DIR=/data
```

`APP_ADMIN_TOKEN` protects the settings and OAuth endpoints; it is deliberately not stored in the database. `DATA_DIR` must be a Railway Volume mount, for example `/data`. Without a volume, a deploy discards the configuration and eventually breaks authorization.

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
- Reply keys are durable, so restarts do not send the same acknowledgement twice. A failed send releases its key for retry.
- Keep polling at one worker/replica. Multiple workers can race both outgoing replies and the single-use refresh-token rotation.
- By default, messages older than ten minutes are ignored to avoid responding to historic conversations after first deployment.
