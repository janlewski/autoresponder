from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import Settings
from .store import Store


class AllegroClient:
    def __init__(self, store: Store, defaults: Settings) -> None:
        self.store, self.defaults = store, defaults
        self._token = ""
        self._token_expiry = datetime.now(timezone.utc)

    @property
    def settings(self) -> Settings:
        return self.store.get_settings(self.defaults)

    @property
    def oauth_base(self) -> str:
        return "https://allegro.pl.allegrosandbox.pl/auth/oauth" if self.settings.environment.startswith("sandbox") else "https://allegro.pl/auth/oauth"

    @property
    def api_base(self) -> str:
        return "https://api.allegro.pl.allegrosandbox.pl" if self.settings.environment.startswith("sandbox") else "https://api.allegro.pl"

    def basic_auth(self) -> str:
        client_id, secret = os.getenv("ALLEGRO_CLIENT_ID", ""), os.getenv("ALLEGRO_CLIENT_SECRET", "")
        if not client_id or not secret:
            raise RuntimeError("Set ALLEGRO_CLIENT_ID and ALLEGRO_CLIENT_SECRET in Railway variables.")
        return "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()

    async def _ensure_token(self) -> str:
        if self._token and datetime.now(timezone.utc) < self._token_expiry:
            return self._token
        # Accept the old environment-only setup on the first boot, then migrate it
        # into the durable store with the first successful token rotation.
        refresh_token = self.store.token("refresh_token") or os.getenv("ALLEGRO_REFRESH_TOKEN", "")
        if not refresh_token:
            raise RuntimeError("Allegro is not connected. Use the Connect Allegro section.")
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(f"{self.oauth_base}/token", headers={"Authorization": self.basic_auth()}, data={"grant_type": "refresh_token", "refresh_token": refresh_token})
            response.raise_for_status()
            payload = response.json()
        # Refresh tokens rotate: persist replacement before any later API call.
        self.store.save_token_response(payload)
        self._token = str(payload["access_token"])
        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=max(30, int(payload.get("expires_in", 43200)) - 120))
        return self._token

    async def _headers(self, beta: bool = False) -> dict[str, str]:
        media_type = "application/vnd.allegro.beta.v1+json" if beta else "application/vnd.allegro.public.v1+json"
        return {"Authorization": f"Bearer {await self._ensure_token()}", "Accept": media_type, "Content-Type": media_type}

    async def request(self, method: str, path: str, *, beta: bool = False, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.request(method, f"{self.api_base}{path}", headers=await self._headers(beta), params=params, json=json)
            response.raise_for_status()
            return response.json() if response.content else {}

    async def list_threads(self, limit: int) -> dict[str, Any]:
        return await self.request("GET", "/messaging/threads", params={"limit": limit, "offset": 0})
    async def list_messages(self, thread_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/messaging/threads/{thread_id}/messages", params={"limit": 20, "offset": 0})
    async def post_message(self, thread_id: str, text: str) -> dict[str, Any]:
        return await self.request("POST", f"/messaging/threads/{thread_id}/messages", json={"text": text})
    async def post_order_message(self, buyer_login: str, order_id: str, text: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/messaging/messages",
            json={
                "recipient": {"login": buyer_login},
                "order": {"id": order_id},
                "text": text,
                "attachments": [],
            },
        )
    async def list_order_events(self, from_event_id: str) -> dict[str, Any]:
        return await self.request("GET", "/order/events", params={"from": from_event_id, "limit": 100})
    async def latest_order_event(self) -> dict[str, Any]:
        return await self.request("GET", "/order/event-stats")
    async def list_issues(self, limit: int) -> dict[str, Any]:
        return await self.request("GET", "/sale/issues", beta=True, params={"limit": limit, "offset": 0})
    async def list_issue_messages(self, issue_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/sale/issues/{issue_id}/chat", beta=True, params={"limit": 100, "offset": 0})
    async def post_issue_message(self, issue_id: str, text: str) -> dict[str, Any]:
        return await self.request("POST", f"/sale/issues/{issue_id}/message", beta=True, json={"text": text, "type": "REGULAR"})
