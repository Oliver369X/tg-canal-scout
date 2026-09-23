"""Informe compacto de fichas guardadas. No devuelve posts ni secretos."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.config import ROOT


def db_path() -> Path:
    return ROOT / "data" / "scout.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def list_saved() -> dict[str, Any]:
    if not db_path().exists():
        return {"ok": False, "error": "no hay scout.db", "fichas": []}
    with _conn() as c:
        fichas = c.execute(
            """
            SELECT id, user_id, peer, title, created_at,
                   length(items_json) AS items_bytes,
                   length(summary_json) AS summary_bytes,
                   summary_json
            FROM fichas
            ORDER BY id
            """
        ).fetchall()
        jobs = c.execute(
            "SELECT ficha_id, mode, running, updated_at FROM scan_jobs"
        ).fetchall()
    out = []
    for row in fichas:
        summary = json.loads(row["summary_json"])
        out.append(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "peer": row["peer"],
                "title": row["title"],
                "created_at": row["created_at"],
                "items_bytes": row["items_bytes"],
                "summary_bytes": row["summary_bytes"],
                "summary": summary,
            }
        )
    return {
        "ok": True,
        "db_bytes": db_path().stat().st_size,
        "fichas": out,
        "jobs": [dict(j) for j in jobs],
    }


def _rows(c: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, params).fetchall()]


def deep_stats(ficha_id: int) -> dict[str, Any]:
    if not db_path().exists():
        return {"ok": False, "error": "no hay scout.db"}
    c = sqlite3.connect(db_path(), timeout=60)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT id, peer, title, length(items_json) AS items_bytes FROM fichas WHERE id=?",
            (ficha_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "ficha no existe"}
        c.execute("DROP TABLE IF EXISTS scan_flat")
        c.execute(
            """
            CREATE TEMP TABLE scan_flat AS
            SELECT
              COALESCE(json_extract(j.value,'$.media'),'empty') AS media,
              lower(COALESCE(json_extract(j.value,'$.mime'),'')) AS mime,
              COALESCE(json_extract(j.value,'$.name'),'') AS name,
              substr(json_extract(j.value,'$.date'),1,7) AS month,
              CAST(substr(json_extract(j.value,'$.date'),12,2) AS INTEGER) AS hour,
              COALESCE(json_extract(j.value,'$.duration'),0) AS duration,
              COALESCE(json_extract(j.value,'$.size'),0) AS size,
              COALESCE(json_extract(j.value,'$.grouped_id'),0) AS grouped_id
            FROM fichas f, json_each(f.items_json) j
            WHERE f.id=?
            """,
            (ficha_id,),
        )

        def top(sql: str, limit: int = 40) -> list[dict[str, Any]]:
            return _rows(c, sql, (limit,))

        media = top("SELECT media AS k, count(*) AS n FROM scan_flat GROUP BY k ORDER BY n DESC LIMIT ?")
        mimes = top("SELECT mime AS k, count(*) AS n FROM scan_flat GROUP BY k ORDER BY n DESC LIMIT ?", 80)
        exts = top(
            """
            SELECT
              CASE
                WHEN name NOT LIKE '%.%' THEN ''
                WHEN lower(name) LIKE '%.mp4' THEN 'mp4'
                WHEN lower(name) LIKE '%.mov' THEN 'mov'
                WHEN lower(name) LIKE '%.mkv' THEN 'mkv'
                WHEN lower(name) LIKE '%.webm' THEN 'webm'
                WHEN lower(name) LIKE '%.jpg' OR lower(name) LIKE '%.jpeg' THEN 'jpg'
                WHEN lower(name) LIKE '%.png' THEN 'png'
                WHEN lower(name) LIKE '%.webp' THEN 'webp'
                WHEN lower(name) LIKE '%.gif' THEN 'gif'
                ELSE 'otro'
              END AS k,
              count(*) AS n
            FROM scan_flat
            GROUP BY k ORDER BY n DESC LIMIT ?
            """
        )
        months = top("SELECT month AS k, count(*) AS n FROM scan_flat GROUP BY k ORDER BY k LIMIT ?", 120)
        hours = top("SELECT hour AS k, count(*) AS n FROM scan_flat GROUP BY k ORDER BY k LIMIT ?", 30)
        dur = top(
            """
            SELECT
              CASE
                WHEN duration = 0 THEN 'sin duracion'
                WHEN duration < 60 THEN '<1 min'
                WHEN duration < 600 THEN '1-10 min'
                WHEN duration < 1800 THEN '10-30 min'
                WHEN duration < 3600 THEN '30-60 min'
                ELSE '>=60 min'
              END AS k,
              count(*) AS n
            FROM scan_flat
            GROUP BY k LIMIT ?
            """
        )
        sizes = top(
            """
            SELECT
              CASE
                WHEN size = 0 THEN 'sin peso'
                WHEN size < 1048576 THEN '<1 MB'
                WHEN size < 10485760 THEN '1-10 MB'
                WHEN size < 104857600 THEN '10-100 MB'
                WHEN size < 524288000 THEN '100-500 MB'
                ELSE '>=500 MB'
              END AS k,
              count(*) AS n
            FROM scan_flat
            GROUP BY k LIMIT ?
            """
        )
        generic = ("video.mp4", "photo.jpg", "document.mp4", "animation.gif", "sticker.webp")
        placeholders = ",".join("?" * len(generic))
        dup_names = _rows(
            c,
            f"""
            SELECT name AS k, count(*) AS n
            FROM scan_flat
            WHERE name != '' AND lower(name) NOT IN ({placeholders})
            GROUP BY name
            HAVING n > 1
            ORDER BY n DESC
            LIMIT 25
            """,
            tuple(generic),
        )
        dup_name_count = dict(
            c.execute(
                f"""
                SELECT count(*) AS groups, COALESCE(sum(n),0) AS posts
                FROM (
                  SELECT count(*) AS n
                  FROM scan_flat
                  WHERE name != '' AND lower(name) NOT IN ({placeholders})
                  GROUP BY name
                  HAVING n > 1
                )
                """,
                tuple(generic),
            ).fetchone()
        )
        generic_names = _rows(
            c,
            f"""
            SELECT lower(name) AS k, count(*) AS n
            FROM scan_flat
            WHERE lower(name) IN ({placeholders})
            GROUP BY k ORDER BY n DESC
            """,
            tuple(generic),
        )
        dup_files = _rows(
            c,
            """
            SELECT mime, size, duration, count(*) AS n
            FROM scan_flat
            WHERE size > 0
            GROUP BY mime, size, duration
            HAVING n > 1
            ORDER BY n DESC
            LIMIT 15
            """,
        )
        dup_file_count = dict(
            c.execute(
                """
                SELECT count(*) AS groups, COALESCE(sum(n),0) AS posts
                FROM (
                  SELECT count(*) AS n
                  FROM scan_flat
                  WHERE size > 0
                  GROUP BY mime, size, duration
                  HAVING n > 1
                )
                """
            ).fetchone()
        )
        named = dict(
            c.execute(
                """
                SELECT
                  sum(CASE WHEN name != '' THEN 1 ELSE 0 END) AS with_name,
                  sum(CASE WHEN size > 0 THEN 1 ELSE 0 END) AS with_size,
                  sum(CASE WHEN duration > 0 THEN 1 ELSE 0 END) AS with_duration,
                  sum(CASE WHEN grouped_id != 0 THEN 1 ELSE 0 END) AS in_album,
                  count(DISTINCT CASE WHEN grouped_id != 0 THEN grouped_id END) AS albums,
                  count(*) AS posts
                FROM scan_flat
                """
            ).fetchone()
        )
        return {
            "ok": True,
            "id": row["id"],
            "peer": row["peer"],
            "title": row["title"],
            "items_bytes": row["items_bytes"],
            "coverage": named,
            "media": media,
            "mimes": mimes,
            "extensions": exts,
            "months": months,
            "hours_utc": hours,
            "duration_buckets": dur,
            "size_buckets": sizes,
            "generic_names": generic_names,
            "duplicate_names_top": dup_names,
            "duplicate_name_groups": dup_name_count,
            "duplicate_same_file_top": dup_files,
            "duplicate_file_groups": dup_file_count,
        }
    finally:
        c.close()
