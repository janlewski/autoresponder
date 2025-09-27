from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .config import Settings


class Decision:
    def __init__(
        self, should_reply: bool, message: Optional[str] = None, reason: str = ""
    ) -> None:
        self.should_reply = should_reply
        self.message = message
        self.reason = reason


def is_working_time(now: datetime, settings: Settings) -> bool:
    h = now.astimezone(settings.tz).hour
    return settings.work_hours_start <= h < settings.work_hours_end


def decide_autoreply(
    *,
    now: datetime,
    msg_time: datetime,
    settings: Settings,
    is_issue: bool = False,
) -> Decision:
    if now - msg_time > timedelta(minutes=10):
        return Decision(False, reason="message too old")
    if is_issue:
        return Decision(True, settings.autoresponse_issue, reason="issue")
    else:
        return Decision(True, settings.autoresponse_message, reason="ask message")
