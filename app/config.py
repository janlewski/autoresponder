from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    # Allegro API
    client_id: str = Field(default_factory=lambda: os.getenv("ALLEGRO_CLIENT_ID", ""))
    client_secret: str = Field(
        default_factory=lambda: os.getenv("ALLEGRO_CLIENT_SECRET", "")
    )
    refresh_token: str = Field(
        default_factory=lambda: os.getenv("ALLEGRO_REFRESH_TOKEN", "")
    )

    environment: str = Field(
        default_factory=lambda: os.getenv("ALLEGRO_ENV", "production")
    )

    # Polling
    poll_interval_seconds: int = Field(
        default_factory=lambda: int(os.getenv("POLL_INTERVAL", "60"))
    )
    max_threads_per_poll: int = Field(
        default_factory=lambda: int(os.getenv("MAX_THREADS", "5"))
    )
    max_issues_per_poll: int = Field(
        default_factory=lambda: int(os.getenv("MAX_ISSUES", "5"))
    )

    # Business rules
    tz: ZoneInfo = Field(default=ZoneInfo(os.getenv("BUSINESS_TZ", "Europe/Warsaw")))
    work_hours_start: int = Field(
        default_factory=lambda: int(os.getenv("WORK_START_H", "9"))
    )
    work_hours_end: int = Field(
        default_factory=lambda: int(os.getenv("WORK_END_H", "17"))
    )

    # Templates
    autoresponse_message: str = Field(
        default_factory=lambda: os.getenv(
            "TEMPLATE_FIRST_CONTACT",
            "Dziękujemy za kontakt! Wkrótce wrócimy z odpowiedzią. \
                Wiadomość automatyczna)",
        )
    )
    autoresponse_issue: str = Field(
        default_factory=lambda: os.getenv(
            "TEMPLATE_ISSUE",
            "Dziękujemy za zgłoszenie problemu. Sprawdzimy sprawę i wkrótce się \
                z Tobą skontaktujemy.",
        )
    )

    # Behavior switches
    reply_outside_working_hours: bool = Field(
        default_factory=lambda: os.getenv("REPLY_AFTER_HOURS", "true").lower() == "true"
    )
    reply_only_first_message: bool = Field(
        default_factory=lambda: os.getenv("REPLY_ONLY_FIRST", "true").lower() == "true"
    )
    process_issues: bool = Field(
        default_factory=lambda: os.getenv("PROCESS_ISSUES", "true").lower() == "true"
    )


def get_settings() -> Settings:
    return Settings()
