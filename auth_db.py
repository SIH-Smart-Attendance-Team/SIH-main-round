"""
auth_db.py – SQLite-backed user persistence layer.

Provides a simple, thread-safe interface around a local SQLite file so that
user accounts (email, password hash, name) survive application restarts.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager

logger = logging.getLogger("weathergpt.auth_db")

DB_PATH = "users.db"

_lock = threading.Lock()


def init_db(db_path: str | None = None) -> None:
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name          TEXT
            )
            """
        )
        conn.commit()
    logger.info("Auth DB initialised at %s", DB_PATH)


@contextmanager
def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_user(user_id: str, email: str, password_hash: str, name: str | None = None) -> bool:
    with _lock:
        with _get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (id, email, password_hash, name) VALUES (?, ?, ?, ?)",
                    (user_id, email, password_hash, name or ""),
                )
                logger.info("Created user: %s", email)
                return True
            except sqlite3.IntegrityError:
                logger.warning("Duplicate signup attempt for %s", email)
                return False


def get_user_by_email(email: str) -> dict[str, str] | None:
    with _lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, name FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def get_user_by_id(user_id: str) -> dict[str, str] | None:
    with _lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash, name FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def count_users() -> int:
    with _lock, _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
        return row["c"] if row else 0
