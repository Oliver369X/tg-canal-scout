"""Estadística y sello por archivo, leídos de los posts ya guardados."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


def _num(n: float | int | None) -> str:
    if n is None:
        return "—"
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if abs(n) >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    if abs(n - int(n)) < 0.05:
        return str(int(round(n)))
    return f"{n:.1f}"


def _mb(n: int | None) -> str:
    if not n:
        return "—"
    mb = int(n) / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    if mb >= 10:
        return f"{mb:.0f} MB"
    return f"{mb:.1f} MB"


def _mins(sec: float | int | None) -> str:
    if not sec:
        return "—"
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    h, rem = divmod(sec, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m} min"


def _link(peer: str, msg_id: int) -> str:
    u = (peer or "").lstrip("@")
    if u.lstrip("-").isdigit():
        cid = u[4:] if u.startswith("-100") else u
        return f"https://t.me/c/{cid}/{msg_id}"
    return f"https://t.me/{u}/{msg_id}"


def _chunks(lines: list[str], limit: int = 3500) -> list[str]:
    out: list[str] = []
    buf = ""
    for line in lines:
        piece = line if not buf else f"{buf}\n{line}"
        if len(piece) > limit and buf:
            out.append(buf)
            buf = line
        else:
            buf = piece
    if buf:
        out.append(buf)
    return out or ["Sin datos."]


def _stamp(item: dict[str, Any]) -> str:
    bits = [_mb(item.get("size")), _mins(item.get("duration"))]
    mime = item.get("mime") or item.get("media") or "archivo"
    bits.append(str(mime))
    w, h = item.get("w"), item.get("h")
    if w and h:
        bits.append(f"{w}×{h}")
    name = (item.get("name") or "").strip()
    if name:
        bits.append(name[:40])
    if item.get("fid"):
        bits.append(f"id {item['fid']}")
    return " · ".join(bits)


def _res(w: int | None, h: int | None) -> str | None:
    if not w or not h:
        return None
    long = max(int(w), int(h))
    if long >= 1920:
        return "1080p+"
    if long >= 1280:
        return "720p"
    if long >= 854:
        return "480p"
    return "menor"


def build_stats(items: list[dict[str, Any]], peer: str, title: str = "") -> dict[str, list[str]]:
    n = len(items)
    media: Counter[str] = Counter()
    mimes: Counter[str] = Counter()
    months: Counter[str] = Counter()
    years: Counter[str] = Counter()
    dur_b: Counter[str] = Counter()
    size_b: Counter[str] = Counter()
    res: Counter[str] = Counter()
    albums: set[int] = set()
    in_album = edited = with_name = with_fid = 0
    video_seconds = 0
    size_total = 0
    heaviest: list[dict[str, Any]] = []
    longest: list[dict[str, Any]] = []
    dup: dict[tuple, dict[str, Any]] = {}

    for item in items:
        kind = item.get("media") or "empty"
        media[kind] += 1
        mime = (item.get("mime") or "").lower()
        if mime:
            mimes[mime] += 1
        date = item.get("date") or ""
        if len(date) >= 7:
            months[date[:7]] += 1
            years[date[:4]] += 1
        bucket = _res(item.get("w"), item.get("h"))
        if bucket:
            res[bucket] += 1
        gid = item.get("grouped_id")
        if gid:
            in_album += 1
            albums.add(int(gid))
        if item.get("edited"):
            edited += 1
        if (item.get("name") or "").strip():
            with_name += 1
        if item.get("fid"):
            with_fid += 1
        dur = int(item.get("duration") or 0)
        size = int(item.get("size") or 0)
        if kind in {"video", "gif", "round"} and dur:
            video_seconds += dur
        if size:
            size_total += size
        if dur == 0:
            dur_b["sin duración"] += 1
        elif dur < 60:
            dur_b["<1 min"] += 1
        elif dur < 600:
            dur_b["1–10 min"] += 1
        elif dur < 1800:
            dur_b["10–30 min"] += 1
        elif dur < 3600:
            dur_b["30–60 min"] += 1
        else:
            dur_b["≥60 min"] += 1
        if size == 0:
            size_b["sin peso"] += 1
        elif size < 1_048_576:
            size_b["<1 MB"] += 1
        elif size < 10_485_760:
            size_b["1–10 MB"] += 1
        elif size < 104_857_600:
            size_b["10–100 MB"] += 1
        elif size < 524_288_000:
            size_b["100–500 MB"] += 1
        else:
            size_b["≥500 MB"] += 1
        if size:
            heaviest.append(item)
        if dur:
            longest.append(item)
        if size and (dur or item.get("fid")):
            key = ("fid", item["fid"]) if item.get("fid") else (mime, size, dur)
            slot = dup.get(key)
            if slot is None:
                dup[key] = {"n": 1, "item": item}
            else:
                slot["n"] += 1

    heaviest.sort(key=lambda i: int(i.get("size") or 0), reverse=True)
    longest.sort(key=lambda i: int(i.get("duration") or 0), reverse=True)
    dup_groups = [v for v in dup.values() if v["n"] > 1]
    dup_groups.sort(key=lambda v: v["n"], reverse=True)
    dup_posts = sum(v["n"] for v in dup_groups)

    head = title or peer or "canal"
    overview = [
        f"Estadística — {head}",
        "Leída de la base. No volví a escanear ni bajé archivos.",
        f"Posts: {_num(n)}",
        f"En álbum: {_num(in_album)} ({_num(len(albums))} álbumes) · sueltos: {_num(n - in_album)}",
        f"Editados: {_num(edited)}",
        f"Peso total del canal: {_mb(size_total)} (dato del archivo, no bajado)",
        f"Video declarado: {_mins(video_seconds)}",
        f"Con nombre de archivo: {_num(with_name)} · con id de archivo: {_num(with_fid)}",
        "",
        "Tipo",
    ]
    for key, count in media.most_common():
        if count:
            overview.append(f"· {key}: {_num(count)}")
    overview += ["", "Formato (MIME), todos"]
    if mimes:
        for mime, count in mimes.most_common():
            overview.append(f"· {mime}: {_num(count)}")
    else:
        overview.append("· sin mime guardado")
    if res:
        overview += ["", "Resolución"]
        for key, count in res.most_common():
            overview.append(f"· {key}: {_num(count)}")
    overview += ["", "Duración"]
    for key in ("<1 min", "1–10 min", "10–30 min", "30–60 min", "≥60 min", "sin duración"):
        if dur_b.get(key):
            overview.append(f"· {key}: {_num(dur_b[key])}")
    overview += ["", "Peso"]
    for key in ("<1 MB", "1–10 MB", "10–100 MB", "100–500 MB", "≥500 MB", "sin peso"):
        if size_b.get(key):
            overview.append(f"· {key}: {_num(size_b[key])}")
    if years:
        overview += ["", "Por año"]
        for year, count in sorted(years.items()):
            overview.append(f"· {year}: {_num(count)}")
    if months:
        overview += ["", "Meses con más posts"]
        for month, count in months.most_common(8):
            overview.append(f"· {month}: {_num(count)}")

    files = [
        f"Sello por archivo — {head}",
        "Cada línea es el caché de Telegram: peso, duración, tipo, resolución y nombre.",
        "No es un hash del video. El id único de Telegram solo aparece si ese escaneo lo guardó.",
        "",
        "Más pesados",
    ]
    for item in heaviest[:12]:
        files.append(f"· {_stamp(item)} — {_link(peer, int(item['id']))}")
    if not heaviest:
        files.append("· ninguno con peso")
    files += ["", "Más largos"]
    for item in longest[:12]:
        files.append(f"· {_stamp(item)} — {_link(peer, int(item['id']))}")
    if not longest:
        files.append("· ninguno con duración")
    files += [
        "",
        f"Repetidos: {_num(len(dup_groups))} grupos · {_num(dup_posts)} posts",
    ]
    if with_fid:
        files.append("Agrupados por id de archivo de Telegram.")
    else:
        files.append("Mismo peso y misma duración. En video es una pista fuerte; en foto, solo un candidato.")
    for group in dup_groups[:12]:
        item = group["item"]
        files.append(f"· ×{group['n']} {_stamp(item)} — {_link(peer, int(item['id']))}")
    if not dup_groups:
        files.append("· no vi grupos repetidos con peso y duración")

    return {"overview": _chunks(overview), "files": _chunks(files)}


def _hit(item: dict[str, Any], peer: str, label: str) -> str:
    return f"· {label} · {_stamp(item)} — {_link(peer, int(item['id']))}"


def _top(items: list[dict[str, Any]], key: str, limit: int = 8) -> list[dict[str, Any]]:
    picked = [i for i in items if int(i.get(key) or 0) > 0]
    picked.sort(key=lambda i: int(i.get(key) or 0), reverse=True)
    return picked[:limit]


def build_classifiers(items: list[dict[str, Any]], peer: str, title: str = "") -> list[str]:
    head = title or peer or "canal"
    views = sorted(int(i["views"]) for i in items if i.get("views"))
    median = views[len(views) // 2] if views else 0
    size_total = sum(int(i.get("size") or 0) for i in items)
    lines = [
        f"Clasificadores — {head}",
        "Reglas sobre la base guardada. No bajé archivos.",
        f"Peso total del canal: {_mb(size_total)}",
        f"Posts: {_num(len(items))} · vistas mediana {_num(median)}",
        "",
        "Más vistos",
    ]
    seen = _top(items, "views")
    lines += [_hit(i, peer, f"{_num(i.get('views'))} vistas") for i in seen] or ["· sin vistas"]
    lines += ["", "Más compartidos"]
    shared = _top(items, "forwards")
    lines += [_hit(i, peer, f"{_num(i.get('forwards'))} veces") for i in shared] or ["· nadie los compartió"]
    lines += ["", "Más comentarios"]
    comments = _top(items, "replies")
    lines += [_hit(i, peer, f"{_num(i.get('replies'))} respuestas") for i in comments] or ["· sin comentarios"]
    lines += ["", "Más reacciones"]
    reacted = _top(items, "reactions")
    lines += [_hit(i, peer, f"{_num(i.get('reactions'))} reacciones") for i in reacted] or ["· sin reacciones"]

    shorts = [
        i
        for i in items
        if i.get("media") == "video"
        and 0 < int(i.get("duration") or 0) < 180
        and int(i.get("views") or 0) > 0
    ]
    shorts.sort(key=lambda i: int(i.get("views") or 0), reverse=True)
    lines += ["", "Videos cortos (<3 min) con más vistas"]
    lines += [_hit(i, peer, f"{_num(i.get('views'))} vistas · {_mins(i.get('duration'))}") for i in shorts[:8]] or [
        "· ninguno"
    ]

    heavy = [
        i
        for i in items
        if i.get("media") == "video"
        and int(i.get("duration") or 0) >= 600
        and int(i.get("size") or 0) >= 100 * 1024 * 1024
    ]
    heavy.sort(key=lambda i: int(i.get("size") or 0), reverse=True)
    lines += ["", "Largos y pesados (≥10 min y ≥100 MB)"]
    lines += [_hit(i, peer, f"{_mins(i.get('duration'))} · {_mb(i.get('size'))}") for i in heavy[:8]] or ["· ninguno"]

    loose = [i for i in items if not i.get("grouped_id") and i.get("urls")]
    loose.sort(key=lambda i: int(i.get("views") or 0), reverse=True)
    lines += ["", "Sueltos con link (fuera de álbum)"]
    lines += [_hit(i, peer, f"{len(i.get('urls') or [])} links") for i in loose[:8]] or ["· ninguno"]

    dup: dict[tuple, dict[str, Any]] = {}
    for item in items:
        if item.get("media") != "video":
            continue
        size = int(item.get("size") or 0)
        dur = int(item.get("duration") or 0)
        if not size or not dur:
            continue
        key = ("fid", item["fid"]) if item.get("fid") else ((item.get("mime") or ""), size, dur)
        slot = dup.get(key)
        if slot is None:
            dup[key] = {"n": 1, "item": item}
        else:
            slot["n"] += 1
    groups = sorted((v for v in dup.values() if v["n"] > 1), key=lambda v: v["n"], reverse=True)
    lines += ["", "Videos repetidos (mismo peso y duración)"]
    if not groups:
        lines.append("· ninguno")
    for group in groups[:8]:
        item = group["item"]
        lines.append(_hit(item, peer, f"×{group['n']}"))
    lines += [
        "",
        "Para ver más, sin espacios: /pedirvistos30 · /pedirmenos20 · /pedirduracion10-40 · /mas",
    ]
    return _chunks(lines)


_ALIASES = {
    "vistos": "vistos",
    "visto": "vistos",
    "masvistos": "vistos",
    "másvistos": "vistos",
    "menos": "menos",
    "menosvistos": "menos",
    "menosvisto": "menos",
    "compartidos": "compartidos",
    "reenvios": "compartidos",
    "reenvíos": "compartidos",
    "comentarios": "comentarios",
    "respuestas": "comentarios",
    "reacciones": "reacciones",
    "duracion": "duracion",
    "duración": "duracion",
    "minutos": "duracion",
    "etiqueta": "etiqueta",
    "tag": "etiqueta",
    "hashtag": "etiqueta",
    "etiquetas": "etiquetas",
    "tags": "etiquetas",
}

_GLUED = (
    ("etiquetas", re.compile(r"^eti(?:qu|k)etas$")),
    ("duracion", re.compile(r"^duracion(\d+)(?:a|-)(\d+)(?:(?:a|-)(\d+))?$")),
    ("etiqueta", re.compile(r"^eti(?:qu|k)eta([a-z0-9_]+?)(?:-(\d+))?$")),
    ("vistos", re.compile(r"^(?:mas)?visto?s?(\d+)?$")),
    ("menos", re.compile(r"^menos(?:visto?s?)?(\d+)?$")),
    ("compartidos", re.compile(r"^compartidos(\d+)?$")),
    ("comentarios", re.compile(r"^comentarios(\d+)?$")),
    ("reacciones", re.compile(r"^reacciones(\d+)?$")),
)


def parse_pedir_args(args: list[str]) -> dict[str, Any] | None:
    if not args:
        return None
    word = args[0].lower().lstrip("/")
    rest = args[1:]
    nums: list[int] = []
    words: list[str] = []
    for raw in rest:
        piece = raw.lstrip("#")
        if piece.isdigit():
            nums.append(int(piece))
        elif piece:
            words.append(piece)
    kind = _ALIASES.get(word)
    if not kind:
        return None
    limit = 10
    min_min = None
    max_min = None
    tag = None
    if kind == "duracion":
        if not nums:
            return None
        min_min = nums[0]
        max_min = nums[1] if len(nums) > 1 else None
        if len(nums) > 2:
            limit = nums[2]
    elif kind == "etiqueta":
        if not words:
            return None
        tag = words[0]
        if nums:
            limit = nums[0]
    elif kind != "etiquetas" and nums:
        limit = nums[0]
    return {"kind": kind, "offset": 0, "limit": limit, "min_min": min_min, "max_min": max_min, "tag": tag}


def _parse_glued(body: str) -> dict[str, Any] | None:
    for kind, rx in _GLUED:
        match = rx.match(body)
        if not match:
            continue
        if kind == "etiquetas":
            return {"kind": kind, "offset": 0, "limit": 10, "min_min": None, "max_min": None, "tag": None}
        if kind == "duracion":
            return {
                "kind": kind,
                "offset": 0,
                "limit": int(match.group(3) or 10),
                "min_min": int(match.group(1)),
                "max_min": int(match.group(2)),
                "tag": None,
            }
        if kind == "etiqueta":
            return {
                "kind": kind,
                "offset": 0,
                "limit": int(match.group(2) or 10),
                "min_min": None,
                "max_min": None,
                "tag": match.group(1),
            }
        return {
            "kind": kind,
            "offset": 0,
            "limit": int(match.group(1) or 10),
            "min_min": None,
            "max_min": None,
            "tag": None,
        }
    return None


def parse_pedir_text(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None
    parts = raw.split()
    head = parts[0].split("@", 1)[0][1:].lower()
    tail = parts[1:]
    if head in {"mas", "más"}:
        limit = int(tail[0]) if tail and tail[0].isdigit() else None
        return {"mas": True, "limit": limit}
    if head == "pedir":
        return parse_pedir_args(tail)
    if head.startswith("pedir_"):
        return parse_pedir_args([p for p in head[6:].split("_") if p] + tail)
    if head.startswith("pedir"):
        return _parse_glued(head[5:])
    return None


def query_posts(
    items: list[dict[str, Any]],
    peer: str,
    *,
    kind: str,
    offset: int = 0,
    limit: int = 10,
    min_min: int | None = None,
    max_min: int | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 10), 40))
    offset = max(0, int(offset or 0))
    title = "Lista"
    picked: list[dict[str, Any]] = []

    if kind == "etiquetas":
        counts: Counter[str] = Counter()
        for item in items:
            for raw in item.get("hashtags") or []:
                name = str(raw).lstrip("#").lower()
                if name:
                    counts[name] += 1
        rows = counts.most_common()
        page = rows[offset : offset + limit]
        lines = [
            "Etiquetas guardadas",
            f"{len(rows)} distintas",
            f"{offset + 1}-{offset + len(page)} de {len(rows)}" if page else f"No hay más. Había {len(rows)}.",
        ]
        lines += [f"· #{name} ({n}) · /pedir etiqueta {name}" for name, n in page]
        if not page:
            lines.append("· ninguna")
        elif offset + limit < len(rows):
            lines.append("Pedí /mas para las siguientes.")
        else:
            lines.append("Fin de esta lista.")
        return {"parts": _chunks(lines), "total": len(rows), "offset": offset, "limit": limit}

    if kind == "duracion":
        lo_m = int(min_min or 0)
        hi_m = int(max_min) if max_min is not None else None
        if hi_m is not None and hi_m < lo_m:
            lo_m, hi_m = hi_m, lo_m
        lo = lo_m * 60
        hi = hi_m * 60 if hi_m is not None else None
        picked = [
            i
            for i in items
            if i.get("media") == "video"
            and int(i.get("duration") or 0) >= lo
            and (hi is None or int(i.get("duration") or 0) <= hi)
        ]
        picked.sort(key=lambda i: int(i.get("duration") or 0))
        title = f"Videos de {lo_m} a {hi_m} min" if hi_m is not None else f"Videos desde {lo_m} min"
    elif kind == "etiqueta":
        needle = (tag or "").lstrip("#").lower()
        picked = [
            i
            for i in items
            if any(str(t).lstrip("#").lower() == needle for t in (i.get("hashtags") or []))
        ]
        picked.sort(key=lambda i: int(i.get("views") or 0), reverse=True)
        title = f"Etiqueta #{needle}"
    elif kind == "menos":
        picked = [i for i in items if i.get("views") is not None]
        picked.sort(key=lambda i: (int(i.get("views") or 0), int(i.get("id") or 0)))
        title = "Menos vistos"
    elif kind == "compartidos":
        picked = _ranked(items, "forwards")
        title = "Más compartidos"
    elif kind == "comentarios":
        picked = _ranked(items, "replies")
        title = "Más comentarios"
    elif kind == "reacciones":
        picked = _ranked(items, "reactions")
        title = "Más reacciones"
    else:
        picked = _ranked(items, "views")
        title = "Más vistos"

    total = len(picked)
    page = picked[offset : offset + limit]
    if page:
        lines = [title, f"{offset + 1}-{offset + len(page)} de {total}"]
    else:
        lines = [title, f"No hay más. Había {total}."]
    for item in page:
        lines.append(_hit(item, peer, _query_label(item, kind)))
    if not page:
        lines.append("· ninguno con ese filtro")
    elif offset + limit < total:
        lines.append("Pedí /mas para los siguientes.")
    else:
        lines.append("Fin de esta lista.")
    return {"parts": _chunks(lines), "total": total, "offset": offset, "limit": limit}


def _ranked(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    picked = [i for i in items if int(i.get(key) or 0) > 0]
    picked.sort(key=lambda i: int(i.get(key) or 0), reverse=True)
    return picked


def _query_label(item: dict[str, Any], kind: str) -> str:
    if kind == "menos" or kind == "vistos":
        return f"{_num(item.get('views'))} vistas · {_mins(item.get('duration'))}"
    if kind == "compartidos":
        return f"{_num(item.get('forwards'))} veces"
    if kind == "comentarios":
        return f"{_num(item.get('replies'))} respuestas"
    if kind == "reacciones":
        return f"{_num(item.get('reactions'))} reacciones"
    if kind == "duracion":
        return f"{_mins(item.get('duration'))} · {_num(item.get('views'))} vistas"
    return f"{_num(item.get('views'))} vistas · {_mins(item.get('duration'))}"
