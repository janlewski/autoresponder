from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    """Non-secret configuration; environment variables provide first-run defaults."""

    environment: str = Field(default_factory=lambda: os.getenv("ALLEGRO_ENV", "production"))
    poll_interval_seconds: int = Field(default_factory=lambda: int(os.getenv("POLL_INTERVAL", "60")), ge=30, le=3600)
    max_threads_per_poll: int = Field(default_factory=lambda: int(os.getenv("MAX_THREADS", "20")), ge=1, le=20)
    max_issues_per_poll: int = Field(default_factory=lambda: int(os.getenv("MAX_ISSUES", "20")), ge=1, le=100)
    autoresponse_message: str = Field(default_factory=lambda: os.getenv("TEMPLATE_FIRST_CONTACT", "Dziękujemy za kontakt! Wkrótce wrócimy z odpowiedzią. Wiadomość automatyczna."), min_length=1, max_length=2000)
    autoresponse_issue: str = Field(default_factory=lambda: os.getenv("TEMPLATE_ISSUE", "Dziękujemy za zgłoszenie problemu. Sprawdzimy sprawę i wkrótce się z Tobą skontaktujemy."), min_length=1, max_length=2000)
    autoresponse_order: str = Field(default_factory=lambda: os.getenv("TEMPLATE_ORDER", "Dziękujemy za zakup! Przygotowujemy Twoje zamówienie."), min_length=1, max_length=2000)
    reply_only_first_message: bool = Field(default_factory=lambda: os.getenv("REPLY_ONLY_FIRST", "true").lower() == "true")
    process_issues: bool = Field(default_factory=lambda: os.getenv("PROCESS_ISSUES", "true").lower() == "true")
    process_orders: bool = Field(default_factory=lambda: os.getenv("PROCESS_ORDERS", "true").lower() == "true")

def data_directory() -> Path:
    configured = os.getenv("DATA_DIR")
    return Path(configured) if configured else (Path("/data") if Path("/data").is_dir() else Path(".data"))


def get_settings() -> Settings:
    return Settings()
