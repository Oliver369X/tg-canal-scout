from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.config import ROOT


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (ROOT / "data" / "scout.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS fichas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    peer TEXT NOT NULL,
                    title TEXT,
                    created_at REAL NOT NULL,
                    summary_json TEXT NOT NULL,
                    items_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scan_jobs (
                    ficha_id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    running INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL
                );
                """
            )

    def save_ficha(self, user_id: int, peer: str, title: str, summary: dict, items: list[dict]) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO fichas (user_id, peer, title, created_at, summary_json, items_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, peer, title, time.time(), json.dumps(summary), json.dumps(items)),
            )
            return int(cur.lastrowid)

    def update_ficha(self, ficha_id: int, user_id: int, summary: dict, items: list[dict]) -> None:
        with self._conn() as c:
            c.execute(
                """UPDATE fichas SET title=?, peer=?, summary_json=?, items_json=?
                   WHERE id=? AND user_id=?""",
                (
                    summary.get("title"),
                    summary.get("peer"),
                    json.dumps(summary),
                    json.dumps(items),
                    ficha_id,
                    user_id,
                ),
            )

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "peer": row["peer"],
            "title": row["title"],
            "summary": json.loads(row["summary_json"]),
            "items": json.loads(row["items_json"]),
        }

    def get_ficha(self, ficha_id: int, user_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM fichas WHERE id=? AND user_id=?",
                (ficha_id, user_id),
            ).fetchone()
        return self._row(row) if row else None

    def latest_ficha(self, user_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM fichas WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return self._row(row) if row else None

    def upsert_job(self, ficha_id: int, user_id: int, chat_id: int, mode: str) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO scan_jobs (ficha_id, user_id, chat_id, mode, running, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?)
                   ON CONFLICT(ficha_id) DO UPDATE SET
                     user_id=excluded.user_id,
                     chat_id=excluded.chat_id,
                     mode=excluded.mode,
                     running=1,
                     updated_at=excluded.updated_at""",
                (ficha_id, user_id, chat_id, mode, time.time()),
            )

    def finish_job(self, ficha_id: int) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE scan_jobs SET running=0, updated_at=? WHERE ficha_id=?",
                (time.time(), ficha_id),
            )

    def list_running_jobs(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM scan_jobs WHERE running=1").fetchall()
        return [
            {
                "ficha_id": r["ficha_id"],
                "user_id": r["user_id"],
                "chat_id": r["chat_id"],
                "mode": r["mode"],
            }
            for r in rows
        ]
