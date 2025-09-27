from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from dotenv import set_key

from .config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class AllegroClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token: Optional[str] = None
        self._token_expiry: datetime = datetime.now(timezone.utc)

        if settings.environment.lower().startswith("sandbox"):
            self.api_base = "https://api.allegro.pl.allegrosandbox.pl"
            self.oauth_base = "https://allegro.pl.allegrosandbox.pl/auth/oauth"
        else:
            self.api_base = "https://api.allegro.pl"
            self.oauth_base = "https://allegro.pl/auth/oauth"

    async def _ensure_token(self) -> str:
        if self._token and datetime.now(timezone.utc) < self._token_expiry:
            return self._token

        basic = base64.b64encode(
            f"{self.settings.client_id}:{self.settings.client_secret}".encode()
        ).decode()
        headers = {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.settings.refresh_token,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.oauth_base}/token", headers=headers, data=data
            )
            r.raise_for_status()
            payload = r.json()
            self._token = payload["access_token"]
            # Refresh a bit earlier than exact expiry
            self._token_expiry = datetime.now(timezone.utc) + timedelta(
                seconds=int(payload.get("expires_in", 3600)) - 120
            )

            # Update refresh token if present in response
            new_refresh_token = payload.get("refresh_token")
            if new_refresh_token and new_refresh_token != self.settings.refresh_token:
                self.settings.refresh_token = new_refresh_token
                # Persist to .env if possible
                try:
                    set_key(str(ENV_FILE), "ALLEGRO_REFRESH_TOKEN", new_refresh_token)
                    logger.info("_ensure_token: Updated refresh token in .env file")
                except Exception as e:
                    logger.warning(
                        f"_ensure_token: Failed to update refresh token in .env: {e}"
                    )

            assert self._token, "Failed to obtain access token"
            logger.info("_ensure_token: Obtained new access token")
            return self._token

    async def _headers(self, use_beta: bool = False) -> Dict[str, str]:
        token = await self._ensure_token()
        content_type = (
            "application/vnd.allegro.beta.v1+json"
            if use_beta
            else "application/vnd.allegro.public.v1+json"
        )
        return {
            "Authorization": f"Bearer {token}",
            "Accept": content_type,
            "Content-Type": content_type,
        }

    async def list_threads(self, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        headers = await self._headers()
        url = f"{self.api_base}/messaging/threads?limit={limit}&offset={offset}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            logger.info(
                f"list_threads: Retrieved threads: {len(r.json().get('threads', []))}"
            )
            return r.json()

    async def list_messages(
        self,
        thread_id: str,
        after: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        headers = await self._headers()
        url = f"{self.api_base}/messaging/threads/{thread_id}/messages?\
            limit={limit}&offset={offset}"
        if after:
            from urllib.parse import quote

            url += f"&after={quote(after)}"  # encode safely

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            logger.info(
                f"list_messages: Retrieved messages in {thread_id}: \
                    {len(r.json().get('messages', []))}"
            )
            return r.json()

    async def post_message(self, thread_id: str, text: str) -> Dict[str, Any]:
        headers = await self._headers()
        url = f"{self.api_base}/messaging/threads/{thread_id}/messages"
        logger.info(f"post_message: Posting message to {thread_id}: {text}")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=headers, json={"text": text})
            r.raise_for_status()
            logger.info(f"post_message: Successfully posted message to {thread_id}")
            return r.json()

    async def list_issues(self, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        """List post-purchase issues/disputes."""
        headers = await self._headers(use_beta=True)
        url = f"{self.api_base}/sale/issues?limit={limit}&offset={offset}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            logger.info(
                f"list_issues: Retrieved issues: {len(r.json().get('issues', []))}"
            )
            return r.json()

    async def list_issue_messages(
        self, issue_id: str, limit: int = 20, offset: int = 0
    ) -> Dict[str, Any]:
        """List messages for a specific issue."""
        headers = await self._headers(use_beta=True)
        url = (
            f"{self.api_base}/sale/issues/{issue_id}/chat?limit={limit}&offset={offset}"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            message_count = len(r.json().get("chat", []))
            logger.info(
                f"list_issue_messages: Retrieved messages for issue {issue_id}: "
                f"{message_count}"
            )
            return r.json()

    async def post_issue_message(self, issue_id: str, text: str) -> Dict[str, Any]:
        """Post a message to an issue."""
        headers = await self._headers(use_beta=True)
        url = f"{self.api_base}/sale/issues/{issue_id}/message"
        payload = {"text": text, "type": "REGULAR"}
        logger.info(f"post_issue_message: Posting message to issue {issue_id}: {text}")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            logger.info(
                f"post_issue_message: Successfully posted message to issue {issue_id}"
            )
            return r.json()
