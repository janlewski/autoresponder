from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

load_dotenv()


class Settings(BaseModel):
    """Non-secret configuration; environment variables provide first-run defaults."""

    environment: str = Field(default_factory=lambda: os.getenv("ALLEGRO_ENV", "production"))
    poll_interval_seconds: int = Field(default_factory=lambda: int(os.getenv("POLL_INTERVAL", "60")), ge=30, le=3600)
    max_threads_per_poll: int = Field(default_factory=lambda: int(os.getenv("MAX_THREADS", "20")), ge=1, le=20)
    max_issues_per_poll: int = Field(default_factory=lambda: int(os.getenv("MAX_ISSUES", "20")), ge=1, le=100)
    work_hours_start: int = Field(default_factory=lambda: int(os.getenv("WORK_START_H", "9")), ge=0, le=23)
    work_hours_end: int = Field(default_factory=lambda: int(os.getenv("WORK_END_H", "17")), ge=1, le=24)
    timezone_name: str = Field(default_factory=lambda: os.getenv("BUSINESS_TZ", "Europe/Warsaw"))
    autoresponse_message: str = Field(default_factory=lambda: os.getenv("TEMPLATE_FIRST_CONTACT", "Dziękujemy za kontakt! Wkrótce wrócimy z odpowiedzią. Wiadomość automatyczna."), min_length=1, max_length=2000)
    autoresponse_issue: str = Field(default_factory=lambda: os.getenv("TEMPLATE_ISSUE", "Dziękujemy za zgłoszenie problemu. Sprawdzimy sprawę i wkrótce się z Tobą skontaktujemy."), min_length=1, max_length=2000)
    autoresponse_order: str = Field(default_factory=lambda: os.getenv("TEMPLATE_ORDER", "Dziękujemy za zakup! Przygotowujemy Twoje zamówienie."), min_length=1, max_length=2000)
    reply_outside_working_hours: bool = Field(default_factory=lambda: os.getenv("REPLY_AFTER_HOURS", "true").lower() == "true")
    reply_only_first_message: bool = Field(default_factory=lambda: os.getenv("REPLY_ONLY_FIRST", "true").lower() == "true")
    process_issues: bool = Field(default_factory=lambda: os.getenv("PROCESS_ISSUES", "true").lower() == "true")
    process_orders: bool = Field(default_factory=lambda: os.getenv("PROCESS_ORDERS", "true").lower() == "true")

    @field_validator("timezone_name")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def valid_working_hours(self) -> Settings:
        if self.work_hours_start >= self.work_hours_end:
            raise ValueError("work_hours_start must be before work_hours_end")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


def data_directory() -> Path:
    configured = os.getenv("DATA_DIR")
    return Path(configured) if configured else (Path("/data") if Path("/data").is_dir() else Path(".data"))


def get_settings() -> Settings:
    return Settings()
