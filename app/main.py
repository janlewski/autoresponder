from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .allegro import AllegroClient
from .config import Settings, data_directory, get_settings
from .rules import decide_autoreply
from .store import Store

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)
defaults = get_settings()
store = Store(data_directory())
client = AllegroClient(store, defaults)
app = FastAPI(title="Allegro Autoresponder", docs_url=None, redoc_url=None)
bearer = HTTPBearer(auto_error=False)
poll_task: asyncio.Task[None] | None = None
recent_fetches: dict[str, Any] = {
    "fetched_at": None,
    "messages": [],
    "issues": [],
    "purchases": [],
}


def settings() -> Settings:
    return store.get_settings(defaults)


def oauth_error(response: httpx.Response) -> str:
    """Return only Allegro's OAuth error fields; never expose response bodies or secrets."""
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        description = payload.get("error_description")
        if isinstance(error, str) and isinstance(description, str):
            return f"{error}: {description}"
        if isinstance(error, str):
            return error
    return f"HTTP {response.status_code}"


async def admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:  # noqa: B008
    token = os.getenv("APP_ADMIN_TOKEN", "")
    if token and (credentials is None or credentials.credentials != token):
        raise HTTPException(status_code=401, detail="Use Authorization: Bearer APP_ADMIN_TOKEN")


async def process_threads(now: datetime, config: Settings) -> None:
    payload = await client.list_threads(config.max_threads_per_poll)
    fetched_messages: list[dict[str, Any]] = []
    for thread in payload.get("threads", payload.get("items", [])) or []:
        thread_id = thread.get("id") or thread.get("thread", {}).get("id")
        if not thread_id:
            continue
        messages = (await client.list_messages(thread_id)).get("messages", [])
        fetched_messages.append({"thread": thread, "messages": messages})
        if not messages:
            continue
        first = min(messages, key=lambda message: message.get("createdAt", ""))
        if (
            not first.get("author", {}).get("isInterlocutor")
            or first.get("type") != "ASK_QUESTION"
        ):
            continue
        message_id = first.get("id") or first.get("createdAt")
        created = datetime.fromisoformat(first.get("createdAt", now.isoformat()).replace("Z", "+00:00"))
        decision = decide_autoreply(now=now, msg_time=created, settings=config)
        key = f"thread:{thread_id}:{message_id}"
        if (
            not config.debug_read_only
            and decision.should_reply
            and decision.message
            and store.claim_processed(key)
        ):
            try:
                await client.post_message(thread_id, decision.message)
                logger.info("Replied to thread %s", thread_id)
            except Exception:
                store.remove_processed(key)
                raise
    recent_fetches["messages"] = fetched_messages


async def process_issues(now: datetime, config: Settings) -> None:
    if not config.process_issues and not config.debug_read_only:
        return
    payload = await client.list_issues(config.max_issues_per_poll)
    fetched_issues: list[dict[str, Any]] = []
    for issue in payload.get("issues", []) or []:
        issue_id = issue.get("id")
        if not issue_id:
            continue
        messages = (await client.list_issue_messages(issue_id)).get("chat", [])
        fetched_issues.append({"issue": issue, "messages": messages})
        if not messages:
            continue
        # Allegro returns issue chat newest-first; select the first message explicitly.
        first = min(messages, key=lambda message: message.get("createdAt", ""))
        if first.get("author", {}).get("role") != "BUYER":
            continue
        message_id = first.get("id") or first.get("createdAt")
        created = datetime.fromisoformat(first.get("createdAt", now.isoformat()).replace("Z", "+00:00"))
        decision = decide_autoreply(now=now, msg_time=created, settings=config, is_issue=True)
        key = f"issue:{issue_id}:{message_id}"
        if (
            not config.debug_read_only
            and decision.should_reply
            and decision.message
            and store.claim_processed(key)
        ):
            try:
                await client.post_issue_message(issue_id, decision.message)
                logger.info("Replied to issue %s", issue_id)
            except Exception:
                store.remove_processed(key)
                raise
    recent_fetches["issues"] = fetched_issues


async def process_orders(config: Settings) -> None:
    """Send one transaction-linked acknowledgement for each newly seen purchase."""
    if not config.process_orders and not config.debug_read_only:
        return
    cursor = store.get("order_event_cursor")
    if config.debug_read_only:
        latest = (await client.latest_order_event()).get("latestEvent", {})
        events = (await client.list_order_events(cursor)).get("events", []) if cursor else []
        recent_fetches["purchases"] = [latest, *events] if latest else events
        return
    if not cursor:
        # Begin watching from now. This avoids sending acknowledgements for historic orders
        # the first time the feature is enabled.
        latest = (await client.latest_order_event()).get("latestEvent", {})
        if event_id := latest.get("id"):
            store.set("order_event_cursor", str(event_id))
        return
    events = (await client.list_order_events(cursor)).get("events", []) or []
    for event in events:
        event_id = event.get("id")
        if not event_id:
            continue
        # READY_FOR_PROCESSING means payment is completed (or the buyer chose COD/pickup)
        # and Allegro considers the checkout form ready for fulfilment.
        if event.get("type") == "READY_FOR_PROCESSING":
            order = event.get("order", {})
            order_id = order.get("checkoutForm", {}).get("id")
            buyer_login = order.get("buyer", {}).get("login")
            if not order_id or not buyer_login:
                logger.warning("Skipping purchase event %s because buyer login or order ID is missing", event_id)
            else:
                key = f"order-message:{order_id}"
                if store.claim_processed(key):
                    try:
                        await client.post_order_message(str(buyer_login), str(order_id), config.autoresponse_order)
                        logger.info("Sent purchase acknowledgement for order %s", order_id)
                    except Exception:
                        store.remove_processed(key)
                        raise
        store.set("order_event_cursor", str(event_id))


async def process_once() -> None:
    config = settings()
    now = datetime.now(timezone.utc)
    await process_orders(config)
    await process_threads(now, config)
    await process_issues(now, config)
    recent_fetches["fetched_at"] = now.isoformat()


async def poll_loop() -> None:
    while True:
        try:
            await process_once()
        except Exception:
            logger.exception("Polling failed")
        await asyncio.sleep(settings().poll_interval_seconds)


@app.on_event("startup")
async def startup() -> None:
    global poll_task
    poll_task = asyncio.create_task(poll_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    if poll_task:
        poll_task.cancel()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "connected": bool(store.token("refresh_token"))}


@app.post("/run-once", dependencies=[Depends(admin)])
async def run_once() -> dict[str, bool]:
    await process_once()
    return {"ran": True}


@app.get("/api/settings", dependencies=[Depends(admin)])
async def read_settings() -> dict[str, Any]:
    return settings().model_dump()


@app.put("/api/settings", dependencies=[Depends(admin)])
async def save_settings(request: Request) -> dict[str, bool]:
    try:
        updated = settings().model_dump()
        updated.update(await request.json())
        store.save_settings(Settings.model_validate(updated))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"saved": True}


@app.get("/api/debug/recent", dependencies=[Depends(admin)])
async def recent_debug_data() -> dict[str, Any]:
    """Return the current poll's in-memory data only while read-only debug is enabled."""
    if not settings().debug_read_only:
        raise HTTPException(status_code=404, detail="Read-only debug mode is disabled.")
    return recent_fetches


@app.post("/api/allegro/device", dependencies=[Depends(admin)])
async def start_device_flow() -> dict[str, Any]:
    client_id = os.getenv("ALLEGRO_CLIENT_ID", "")
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(
            f"{client.oauth_base}/device",
            headers={"Authorization": client.basic_auth()},
            data={"client_id": client_id},
        )
    if response.is_error:
        detail = oauth_error(response)
        logger.warning("Allegro Device Flow could not start: %s", detail)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Allegro Device Flow could not start ({detail}). "
                "Confirm that ALLEGRO_CLIENT_ID and ALLEGRO_CLIENT_SECRET belong to an app "
                "registered as a Device Flow application in Allegro."
            ),
        )
    try:
        payload = response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Allegro returned an invalid Device Flow response.") from error
    store.set("device_code", str(payload["device_code"]))
    return {key: payload[key] for key in ("user_code", "verification_uri", "verification_uri_complete", "expires_in", "interval") if key in payload}


@app.post("/api/allegro/device/complete", dependencies=[Depends(admin)])
async def complete_device_flow() -> dict[str, bool]:
    code = store.token("device_code")
    if not code:
        raise HTTPException(status_code=400, detail="Start device authorization first.")
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(f"{client.oauth_base}/token", headers={"Authorization": client.basic_auth()}, data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": code})
    if response.status_code == 400:
        raise HTTPException(status_code=409, detail=response.json().get("error", "Authorization pending"))
    response.raise_for_status()
    store.save_token_response(response.json())
    store.set("device_code", "")
    return {"connected": True}


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).with_name("templates") / "dashboard.html")
