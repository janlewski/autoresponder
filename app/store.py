from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from .config import Settings


class Store:
    """Small durable store for configuration, credentials and idempotency keys."""
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(directory / "autoresponder.sqlite3", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = Lock()
        with self.connection:
            self.connection.executescript("PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS processed (key TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);")

    def get(self, key: str) -> str | None:
        with self.lock:
            row = self.connection.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set(self, key: str, value: str) -> None:
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def get_settings(self, defaults: Settings) -> Settings:
        raw = self.get("settings")
        return Settings.model_validate_json(raw) if raw else defaults

    def save_settings(self, settings: Settings) -> None:
        self.set("settings", settings.model_dump_json())

    def token(self, name: str) -> str:
        return self.get(name) or ""

    def save_token_response(self, response: dict[str, Any]) -> None:
        if refresh_token := response.get("refresh_token"):
            self.set("refresh_token", str(refresh_token))

    def claim_processed(self, key: str) -> bool:
        with self.lock, self.connection:
            return self.connection.execute("INSERT OR IGNORE INTO processed(key) VALUES(?)", (key,)).rowcount == 1

    def remove_processed(self, key: str) -> None:
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM processed WHERE key = ?", (key,))
