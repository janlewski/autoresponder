from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
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
    for thread in payload.get("threads", payload.get("items", [])) or []:
        thread_id = thread.get("id") or thread.get("thread", {}).get("id")
        if not thread_id:
            continue
        messages = (await client.list_messages(thread_id)).get("messages", [])
        if not messages:
            continue
        last = max(messages, key=lambda m: m.get("createdAt", ""))
        if not last.get("author", {}).get("isInterlocutor") or last.get("type") != "ASK_QUESTION":
            continue
        if config.reply_only_first_message and any(
            message is not last and message.get("author", {}).get("isInterlocutor")
            for message in messages
        ):
            continue
        message_id = last.get("id") or last.get("createdAt")
        created = datetime.fromisoformat(last.get("createdAt", now.isoformat()).replace("Z", "+00:00"))
        decision = decide_autoreply(now=now, msg_time=created, settings=config)
        key = f"thread:{thread_id}:{message_id}"
        if decision.should_reply and decision.message and store.claim_processed(key):
            try:
                await client.post_message(thread_id, decision.message)
                logger.info("Replied to thread %s", thread_id)
            except Exception:
                store.remove_processed(key)
                raise


async def process_issues(now: datetime, config: Settings) -> None:
    if not config.process_issues:
        return
    payload = await client.list_issues(config.max_issues_per_poll)
    for issue in payload.get("issues", []) or []:
        issue_id = issue.get("id")
        if not issue_id:
            continue
        messages = (await client.list_issue_messages(issue_id)).get("chat", [])
        if not messages:
            continue
        # Allegro returns issue chat newest-first; choose explicitly to be resilient.
        last = max(messages, key=lambda m: m.get("createdAt", ""))
        if last.get("author", {}).get("role") != "BUYER":
            continue
        if config.reply_only_first_message and any(
            message is not last and message.get("author", {}).get("role") == "BUYER"
            for message in messages
        ):
            continue
        message_id = last.get("id") or last.get("createdAt")
        created = datetime.fromisoformat(last.get("createdAt", now.isoformat()).replace("Z", "+00:00"))
        decision = decide_autoreply(now=now, msg_time=created, settings=config, is_issue=True)
        key = f"issue:{issue_id}:{message_id}"
        if decision.should_reply and decision.message and store.claim_processed(key):
            try:
                await client.post_issue_message(issue_id, decision.message)
                logger.info("Replied to issue %s", issue_id)
            except Exception:
                store.remove_processed(key)
                raise


async def process_once() -> None:
    config = settings()
    now = datetime.now(timezone.utc)
    await process_threads(now, config)
    await process_issues(now, config)


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
        store.save_settings(Settings.model_validate(await request.json()))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"saved": True}


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


PAGE = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Allegro Autoresponder</title><style>body{max-width:720px;margin:40px auto;padding:0 16px;font:16px system-ui;color:#191919}textarea,input{box-sizing:border-box;width:100%;padding:9px;margin:5px 0 16px}textarea{min-height:105px}button{padding:10px 14px;background:#111;color:#fff;border:0;border-radius:5px}section{border-top:1px solid #ddd;margin-top:28px;padding-top:20px}.row{display:flex;gap:18px}.row>*{flex:1}</style></head><body><h1>Allegro Autoresponder</h1><p id="status">Loading…</p><section><h2>Connect Allegro</h2><p>Device flow works through an SSH tunnel and needs no public callback URL.</p><button onclick="connect()">Get Allegro login link</button> <button onclick="complete()">I approved it</button><p id="oauth"></p></section><section><h2>Replies</h2><label>Question reply<textarea id="autoresponse_message"></textarea></label><label>Issue/discussion reply<textarea id="autoresponse_issue"></textarea></label><label><input type="checkbox" id="process_issues"> Respond to issues/discussions</label><label><input type="checkbox" id="reply_only_first_message"> Reply only once per customer message</label><label><input type="checkbox" id="reply_outside_working_hours"> Reply outside working hours</label><div class="row"><label>Poll seconds<input id="poll_interval_seconds" type="number"></label><label>Timezone<input id="timezone_name"></label></div><div class="row"><label>Work day starts<input id="work_hours_start" type="number" min="0" max="23"></label><label>Work day ends<input id="work_hours_end" type="number" min="1" max="24"></label></div><button onclick="save()">Save configuration</button></section><script>let headers={};let token=prompt('Admin token (leave empty if APP_ADMIN_TOKEN is not set)');if(token)headers.Authorization='Bearer '+token;async function api(u,o={}){o.headers={...headers,...(o.headers||{})};let r=await fetch(u,o);if(!r.ok)throw new Error((await r.json()).detail||r.status);return r.json()}async function load(){let s=await api('/api/settings');for(let k in s){let e=document.getElementById(k);if(e)e.type==='checkbox'?e.checked=s[k]:e.value=s[k]}let h=await fetch('/health').then(x=>x.json());status.textContent=h.connected?'Connected and polling.':'Not connected yet.'}async function save(){let s={};for(let k of ['autoresponse_message','autoresponse_issue','process_issues','reply_only_first_message','reply_outside_working_hours','poll_interval_seconds','timezone_name','work_hours_start','work_hours_end']){let e=document.getElementById(k);s[k]=e.type==='checkbox'?e.checked:(['poll_interval_seconds','work_hours_start','work_hours_end'].includes(k)?+e.value:e.value)}let old=await api('/api/settings');Object.assign(old,s);await api('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(old)});alert('Saved')}async function connect(){let x=await api('/api/allegro/device',{method:'POST'});oauth.innerHTML='Open <a target="_blank" href="'+x.verification_uri_complete+'">Allegro login</a> and approve it. Code: <b>'+x.user_code+'</b>'}async function complete(){try{await api('/api/allegro/device/complete',{method:'POST'});await load();alert('Connected')}catch(e){alert(e.message+' — wait a moment and try again.')}}load().catch(e=>status.textContent=e.message)</script></body></html>'''


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return PAGE
