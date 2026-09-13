from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.parse import url_domain

MEDIA_LABELS = {
    "photo": "Fotos",
    "video": "Videos",
    "gif": "GIFs",
    "round": "Notas de video",
    "audio": "Audios",
    "voice": "Notas de voz",
    "file": "Archivos",
    "sticker": "Stickers",
    "poll": "Encuestas",
    "web": "Vista web",
    "text": "Solo texto",
    "contact": "Contactos",
    "geo": "Ubicaciones",
    "service": "Servicio",
    "empty": "Vacío",
}


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def _median(nums: list[int | float]) -> float | None:
    if not nums:
        return None
    s = sorted(nums)
    return float(s[len(s) // 2])


def _avg(nums: list[int | float]) -> float | None:
    if not nums:
        return None
    return sum(nums) / len(nums)


def _res_bucket(w: int | None, h: int | None) -> str | None:
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


def summarize(items: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    n = len(items)
    counts: Counter[str] = Counter()
    urls_all: list[str] = []
    hashtags: list[str] = []
    mentions: list[str] = []
    domains: Counter[str] = Counter()
    mimes: Counter[str] = Counter()
    res: Counter[str] = Counter()
    fwd_from: Counter[str] = Counter()
    albums: set[int] = set()
    views: list[int] = []
    forwards: list[int] = []
    reactions: list[int] = []
    video_durations: list[int] = []
    sizes: list[int] = []
    hours: Counter[int] = Counter()
    with_url = 0
    long_videos = 0
    heavy = 0
    original = 0
    edited = 0
    oldest = newest = None

    for i in items:
        kind = i.get("media") or "empty"
        counts[kind] += 1
        dt = _parse_dt(i.get("date"))
        if dt:
            hours[dt.hour] += 1
            if oldest is None or dt < oldest:
                oldest = dt
            if newest is None or dt > newest:
                newest = dt
        urls = i.get("urls") or []
        if urls:
            with_url += 1
            for u in urls:
                urls_all.append(u)
                d = url_domain(u)
                if d:
                    domains[d] += 1
        for t in i.get("hashtags") or []:
            hashtags.append(t)
        for m in i.get("mentions") or []:
            mentions.append(m)
        mime = (i.get("mime") or "").lower()
        if mime:
            mimes[mime] += 1
        bucket = _res_bucket(i.get("w"), i.get("h"))
        if bucket:
            res[bucket] += 1
        gid = i.get("grouped_id")
        if gid:
            albums.add(int(gid))
        if i.get("views"):
            views.append(int(i["views"]))
        if i.get("forwards"):
            forwards.append(int(i["forwards"]))
        if i.get("reactions"):
            reactions.append(int(i["reactions"]))
        if i.get("fwd"):
            fwd_from[str(i["fwd"])] += 1
        else:
            original += 1
        if i.get("edited"):
            edited += 1
        dur = i.get("duration") or 0
        if kind in {"video", "gif", "round"} and dur:
            video_durations.append(int(dur))
            if dur >= 600:
                long_videos += 1
        size = i.get("size") or 0
        if size:
            sizes.append(int(size))
            if size >= 100 * 1024 * 1024:
                heavy += 1

    days = 1.0
    if oldest and newest:
        days = max((newest - oldest).total_seconds() / 86400, 1 / 24)
    posts_per_day = n / days if n else 0
    peak_hour = hours.most_common(1)[0][0] if hours else None
    tag_counts = Counter(hashtags)
    mention_counts = Counter(mentions)

    out = dict(meta)
    out.update(
        {
            "sampled": n,
            "photos": counts.get("photo", 0),
            "videos": counts.get("video", 0),
            "gifs": counts.get("gif", 0),
            "rounds": counts.get("round", 0),
            "audios": counts.get("audio", 0),
            "voices": counts.get("voice", 0),
            "files": counts.get("file", 0),
            "stickers": counts.get("sticker", 0),
            "polls": counts.get("poll", 0),
            "webs": counts.get("web", 0),
            "texts": counts.get("text", 0),
            "counts": dict(counts),
            "with_url": with_url,
            "url_count": len(urls_all),
            "unique_urls": len(set(urls_all)),
            "videos_ge_10min": long_videos,
            "files_ge_100mb": heavy,
            "albums": len(albums),
            "original": original,
            "forwarded": n - original,
            "edited": edited,
            "oldest": oldest.astimezone(timezone.utc).isoformat() if oldest else None,
            "newest": newest.astimezone(timezone.utc).isoformat() if newest else None,
            "posts_per_day": round(posts_per_day, 2),
            "peak_hour": peak_hour,
            "video_seconds": sum(video_durations),
            "video_duration_avg": _avg(video_durations),
            "video_duration_max": max(video_durations) if video_durations else None,
            "size_total": sum(sizes),
            "size_max": max(sizes) if sizes else None,
            "views_avg": _avg(views),
            "views_median": _median(views),
            "views_max": max(views) if views else None,
            "forwards_avg": _avg(forwards),
            "forwards_max": max(forwards) if forwards else None,
            "reactions_avg": _avg(reactions),
            "top_domains": domains.most_common(8),
            "top_hashtags": tag_counts.most_common(8),
            "top_mentions": mention_counts.most_common(6),
            "top_fwd": fwd_from.most_common(6),
            "resolutions": dict(res),
            "mimes": mimes.most_common(6),
        }
    )
    return out


CHANNEL_META_KEYS = (
    "title",
    "kind",
    "peer",
    "entity_id",
    "members",
    "created",
    "verified",
    "scam",
    "fake",
    "restricted",
    "noforwards",
    "about",
    "linked_chat_id",
    "restriction",
)


def meta_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {k: summary.get(k) for k in CHANNEL_META_KEYS}


def merge_items(old: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {i.get("id") for i in old}
    out = list(old)
    for i in extra:
        mid = i.get("id")
        if mid in seen:
            continue
        out.append(i)
        seen.add(mid)
    return out


def oldest_msg_id(items: list[dict[str, Any]]) -> int:
    ids = [int(i["id"]) for i in items if i.get("id") is not None]
    return min(ids) if ids else 0


def set_paging(
    summary: dict[str, Any],
    *,
    exhausted: bool,
    max_sample: int,
    continue_hint: int = 300,
) -> dict[str, Any]:
    n = int(summary.get("sampled") or 0)
    summary["exhausted"] = bool(exhausted)
    summary["max_sample"] = int(max_sample)
    summary["continue_hint"] = int(continue_hint)
    summary["can_continue"] = (not exhausted) and n < int(max_sample)
    return summary
