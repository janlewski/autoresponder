from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI

from .allegro import AllegroClient
from .config import get_settings
from .rules import decide_autoreply


def parse_timestamp(timestamp_str: Optional[str], fallback: datetime) -> datetime:
    """Safely parse ISO timestamp string to datetime object."""
    if not timestamp_str:
        return fallback
    try:
        return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return fallback


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title="Allegro Autoresponder")
client = AllegroClient(settings)


# background task handle
poll_task: Optional[asyncio.Task] = None


async def poll_loop() -> None:
    interval = settings.poll_interval_seconds
    while True:
        try:
            await process_once()
        except Exception as e:
            # log to stdout (Railway captures logs)
            print(f"[poll] error: {e}")
        await asyncio.sleep(interval)


async def process_once() -> None:
    now = datetime.now(timezone.utc)

    # Process threads
    await process_threads(now)

    # Process issues/disputes
    if settings.process_issues:
        await process_issues(now)


async def process_threads(now: datetime) -> None:
    """Process messaging threads for ASK_QUESTION types."""
    threads_payload = await client.list_threads(
        limit=settings.max_threads_per_poll, offset=0
    )
    threads = (
        threads_payload.get("threads", []) or threads_payload.get("items", []) or []
    )
    logger.info(f"Fetched {len(threads)} threads")

    for th in threads:
        now = datetime.now(timezone.utc)
        thread_id = th.get("id") or th.get("thread", {}).get("id")
        if not thread_id:
            continue

        logger.info(f"[thread {thread_id}] fetching messages...")
        msgs_payload = await client.list_messages(thread_id)
        messages = (
            msgs_payload.get("messages", []) or msgs_payload.get("items", []) or []
        )

        if not messages:
            continue

        # Sort by creation time ascending (if not already)
        def _ts(m: dict) -> str:
            return m.get("createdAt") or m.get("created") or m.get("creationDate") or ""

        messages.sort(key=_ts)

        # Check if the last message is from interlocutor (buyer)
        last_message = messages[-1]
        logger.info(f"[thread {thread_id}] last message: {last_message}")
        is_from_interlocutor = last_message.get("author", {}).get(
            "isInterlocutor", False
        )

        is_ask_type = last_message.get("type", "") == "ASK_QUESTION"

        if not is_from_interlocutor:
            logger.info(
                f"[thread {thread_id}] last message not from interlocutor, skipping"
            )
            continue

        if not is_ask_type:
            logger.info(f"[thread {thread_id}] last message not ASK_QUESTION, skipping")
            continue

        msg_time = parse_timestamp(last_message.get("createdAt"), now)
        decision = decide_autoreply(
            now=now,
            msg_time=msg_time,
            settings=settings,
            is_issue=False,
        )

        logger.info(
            f"[thread {thread_id}] decision: {decision.reason} "
            f"should_reply={decision.should_reply}"
        )

        # Post reply if needed
        if decision.should_reply and decision.message:
            try:
                await client.post_message(thread_id, decision.message)
                logger.info(f"[thread {thread_id}] replied successfully")
            except Exception as e:
                print(f"[thread {thread_id}] post_message error: {e}")


async def process_issues(now: datetime) -> None:
    """Process post-purchase issues/disputes."""
    issues_payload = await client.list_issues(
        limit=settings.max_issues_per_poll, offset=0
    )
    issues = issues_payload.get("issues", []) or []
    logger.info(f"Fetched {len(issues)} issues")

    for issue in issues:
        now = datetime.now(timezone.utc)
        issue_id = issue.get("id")
        if not issue_id:
            continue

        logger.info(f"[issue {issue_id}]: {issue}")
        # Check if issue was just started (has status that indicates new issue)
        current_state = issue.get("currentState")
        status = current_state.get("status") if current_state else None
        if status != "DISPUTE_ONGOING":
            logger.info(f"[issue {issue_id}] status is {status}, skipping")
            continue

        logger.info(f"[issue {issue_id}] processing issue with status: {status}")

        try:
            msgs_payload = await client.list_issue_messages(issue_id)
            messages = msgs_payload.get("chat", []) or []

            if not messages:
                continue

            logger.info(f"[issue {issue_id}] fetched {len(messages)} messages")

            if len(messages) > 2:
                logger.info(f"[issue {issue_id}] more than 2 messages, skipping")
                continue

            # logger.info(f"[issue {issue_id}] messages: {messages}")

            # Sort by creation time ascending
            def _ts(m: dict) -> str:
                return (
                    m.get("createdAt")
                    or m.get("created")
                    or m.get("creationDate")
                    or ""
                )

            messages.sort(key=_ts)

            # Check if the last message is from buyer
            last_message = messages[-1]
            is_from_buyer = last_message.get("author", {}).get("role") == "BUYER"

            if not is_from_buyer:
                logger.info(f"[issue {issue_id}] last message not from buyer, skipping")
                continue

            msg_time = parse_timestamp(last_message.get("createdAt"), now)

            decision = decide_autoreply(
                now=now,
                msg_time=msg_time,
                settings=settings,
                is_issue=True,
            )

            logger.info(
                f"[issue {issue_id}] decision: {decision.reason} "
                f"should_reply={decision.should_reply}"
            )

            # Post reply if needed
            if decision.should_reply and decision.message:
                try:
                    await client.post_issue_message(issue_id, decision.message)
                    logger.info(f"[issue {issue_id}] replied successfully")
                except Exception as e:
                    print(f"[issue {issue_id}] post_issue_message error: {e}")

        except Exception as e:
            print(f"[issue {issue_id}] processing error: {e}")


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Starting up...")
    global poll_task
    # Start background polling
    poll_task = asyncio.create_task(poll_loop())


@app.get("/")
async def root() -> dict:
    return {
        "status": "ok",
        "env": settings.environment,
        "poll_interval": settings.poll_interval_seconds,
        "features": {
            "process_threads": True,
            "process_issues": settings.process_issues,
            "reply_only_first": settings.reply_only_first_message,
            "reply_after_hours": settings.reply_outside_working_hours,
        },
    }


@app.post("/run-once")
async def run_once() -> dict:
    await process_once()
    return {"ran": True}
