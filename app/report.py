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


def deep_stats(ficha_id: int) -> dict[str, Any]:
    if not db_path().exists():
        return {"ok": False, "error": "no hay scout.db"}
    with _conn() as c:
        row = c.execute(
            "SELECT id, peer, title, length(items_json) AS items_bytes FROM fichas WHERE id=?",
            (ficha_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "ficha no existe"}

        def grouped(sql: str, limit: int = 40) -> list[dict[str, Any]]:
            rows = c.execute(sql, (ficha_id, limit)).fetchall()
            return [dict(r) for r in rows]

        base = "FROM fichas f, json_each(f.items_json) j WHERE f.id=?"
        media = grouped(
            f"""
            SELECT COALESCE(json_extract(j.value,'$.media'),'empty') AS k, count(*) AS n
            {base}
            GROUP BY k ORDER BY n DESC LIMIT ?
            """
        )
        mimes = grouped(
            f"""
            SELECT lower(COALESCE(json_extract(j.value,'$.mime'),'')) AS k, count(*) AS n
            {base}
            GROUP BY k ORDER BY n DESC LIMIT ?
            """,
            80,
        )
        exts = grouped(
            f"""
            SELECT lower(
              CASE
                WHEN instr(COALESCE(json_extract(j.value,'$.name'),''), '.') = 0 THEN ''
                ELSE substr(
                  json_extract(j.value,'$.name'),
                  length(json_extract(j.value,'$.name'))
                    - instr(reverse(json_extract(j.value,'$.name')), '.') + 2
                )
              END
            ) AS k, count(*) AS n
            {base}
            GROUP BY k ORDER BY n DESC LIMIT ?
            """,
            40,
        )
        months = grouped(
            f"""
            SELECT substr(json_extract(j.value,'$.date'),1,7) AS k, count(*) AS n
            {base}
            GROUP BY k ORDER BY k LIMIT ?
            """,
            120,
        )
        hours = grouped(
            f"""
            SELECT CAST(substr(json_extract(j.value,'$.date'),12,2) AS INTEGER) AS k, count(*) AS n
            {base}
            GROUP BY k ORDER BY k LIMIT ?
            """,
            30,
        )
        dur = grouped(
            f"""
            SELECT
              CASE
                WHEN COALESCE(json_extract(j.value,'$.duration'),0) = 0 THEN 'sin duracion'
                WHEN json_extract(j.value,'$.duration') < 60 THEN '<1 min'
                WHEN json_extract(j.value,'$.duration') < 600 THEN '1-10 min'
                WHEN json_extract(j.value,'$.duration') < 1800 THEN '10-30 min'
                WHEN json_extract(j.value,'$.duration') < 3600 THEN '30-60 min'
                ELSE '>=60 min'
              END AS k,
              count(*) AS n
            {base}
            GROUP BY k LIMIT ?
            """
        )
        sizes = grouped(
            f"""
            SELECT
              CASE
                WHEN COALESCE(json_extract(j.value,'$.size'),0) = 0 THEN 'sin peso'
                WHEN json_extract(j.value,'$.size') < 1048576 THEN '<1 MB'
                WHEN json_extract(j.value,'$.size') < 10485760 THEN '1-10 MB'
                WHEN json_extract(j.value,'$.size') < 104857600 THEN '10-100 MB'
                WHEN json_extract(j.value,'$.size') < 524288000 THEN '100-500 MB'
                ELSE '>=500 MB'
              END AS k,
              count(*) AS n
            {base}
            GROUP BY k LIMIT ?
            """
        )
        dup_names = grouped(
            f"""
            SELECT json_extract(j.value,'$.name') AS k, count(*) AS n
            {base}
              AND COALESCE(json_extract(j.value,'$.name'),'') != ''
            GROUP BY k
            HAVING n > 1
            ORDER BY n DESC
            LIMIT ?
            """,
            25,
        )
        dup_files = grouped(
            f"""
            SELECT
              json_extract(j.value,'$.mime') AS mime,
              json_extract(j.value,'$.size') AS size,
              json_extract(j.value,'$.duration') AS duration,
              count(*) AS n
            {base}
              AND COALESCE(json_extract(j.value,'$.size'),0) > 0
            GROUP BY mime, size, duration
            HAVING n > 1
            ORDER BY n DESC
            LIMIT ?
            """,
            25,
        )
        dup_name_count = c.execute(
            f"""
            SELECT count(*) AS groups, COALESCE(sum(n),0) AS posts
            FROM (
              SELECT count(*) AS n
              {base}
                AND COALESCE(json_extract(j.value,'$.name'),'') != ''
              GROUP BY json_extract(j.value,'$.name')
              HAVING n > 1
            )
            """,
            (ficha_id,),
        ).fetchone()
        dup_file_count = c.execute(
            f"""
            SELECT count(*) AS groups, COALESCE(sum(n),0) AS posts
            FROM (
              SELECT count(*) AS n
              {base}
                AND COALESCE(json_extract(j.value,'$.size'),0) > 0
              GROUP BY json_extract(j.value,'$.mime'),
                       json_extract(j.value,'$.size'),
                       json_extract(j.value,'$.duration')
              HAVING n > 1
            )
            """,
            (ficha_id,),
        ).fetchone()
        named = c.execute(
            f"""
            SELECT
              sum(CASE WHEN COALESCE(json_extract(j.value,'$.name'),'') != '' THEN 1 ELSE 0 END) AS with_name,
              sum(CASE WHEN COALESCE(json_extract(j.value,'$.size'),0) > 0 THEN 1 ELSE 0 END) AS with_size,
              sum(CASE WHEN COALESCE(json_extract(j.value,'$.duration'),0) > 0 THEN 1 ELSE 0 END) AS with_duration,
              count(*) AS posts
            {base}
            """,
            (ficha_id,),
        ).fetchone()

    return {
        "ok": True,
        "id": row["id"],
        "peer": row["peer"],
        "title": row["title"],
        "items_bytes": row["items_bytes"],
        "coverage": dict(named) if named else {},
        "media": media,
        "mimes": mimes,
        "extensions": exts,
        "months": months,
        "hours_utc": hours,
        "duration_buckets": dur,
        "size_buckets": sizes,
        "duplicate_names_top": dup_names,
        "duplicate_name_groups": dict(dup_name_count) if dup_name_count else {},
        "duplicate_same_file_top": dup_files,
        "duplicate_file_groups": dict(dup_file_count) if dup_file_count else {},
    }
