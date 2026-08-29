from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    """Non-secret configuration; environment variables provide first-run defaults."""

    environment: str = Field(
        default_factory=lambda: os.getenv("ALLEGRO_ENV", "production")
    )
    poll_interval_seconds: int = Field(
        default_factory=lambda: int(os.getenv("POLL_INTERVAL", "60")), ge=30, le=3600
    )
    max_threads_per_poll: int = Field(
        default_factory=lambda: int(os.getenv("MAX_THREADS", "20")), ge=1, le=20
    )
    max_issues_per_poll: int = Field(
        default_factory=lambda: int(os.getenv("MAX_ISSUES", "20")), ge=1, le=100
    )
    autoresponse_message: str = Field(
        default_factory=lambda: os.getenv(
            "TEMPLATE_FIRST_CONTACT",
            "Dziękujemy za kontakt, odpowiemy najszybciej jak to będzie możliwe. \n\nZespół taanio_pl",
        ),
        min_length=1,
        max_length=2000,
    )
    autoresponse_issue: str = Field(
        default_factory=lambda: os.getenv(
            "TEMPLATE_ISSUE",
            "Dziękujemy za zgłoszenie problemu, odpowiemy najszybciej jak to będzie możliwe. \n\nZespół taanio_pl",
        ),
        min_length=1,
        max_length=2000,
    )
    autoresponse_order: str = Field(
        default_factory=lambda: os.getenv(
            "TEMPLATE_ORDER",
            """Dziękujemy za Twoje zamówienie 💛
Bardzo się cieszymy, że wybrałeś właśnie nas.

Każdą paczkę przygotowujemy starannie i wysyłamy najpóźniej w ciągu 3 dni roboczych od zakupu.

🧾 Jeśli podczas składania zamówienia została wybrana faktura, w większości przypadków w paczce znajdziesz paragon z NIP, który jest fakturą uproszczoną.

Mamy nadzieję, że wszystko dotrze do Ciebie szybko i będzie dokładnie takie, jak oczekujesz 😊
Jeśli po odebraniu przesyłki znajdziesz chwilę na wystawienie oceny na Allegro, będzie nam naprawdę bardzo miło — każda opinia ma dla nas duże znaczenie ⭐

Dziękujemy za zaufanie i życzymy samych udanych zakupów 💛""",
        ),
        min_length=1,
        max_length=2000,
    )
    process_issues: bool = Field(
        default_factory=lambda: os.getenv("PROCESS_ISSUES", "true").lower() == "true"
    )
    process_orders: bool = Field(
        default_factory=lambda: os.getenv("PROCESS_ORDERS", "true").lower() == "true"
    )
    debug_read_only: bool = Field(
        default_factory=lambda: os.getenv("DEBUG_READ_ONLY", "false").lower() == "true"
    )


def data_directory() -> Path:
    configured = os.getenv("DATA_DIR")
    return (
        Path(configured)
        if configured
        else (Path("/data") if Path("/data").is_dir() else Path(".data"))
    )


def get_settings() -> Settings:
    return Settings()
