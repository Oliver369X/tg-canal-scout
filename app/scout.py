from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import (
    Channel,
    Chat,
    MessageEntityMention,
    MessageEntityTextUrl,
    MessageEntityUrl,
    User,
)

from app.analyze import meta_from_summary, merge_items, oldest_msg_id, set_paging, summarize
from app.config import get_settings
from app.human_read import iter_history_human
from app.pace import iter_kwargs
from app.parse import extract_hashtags, extract_urls, parse_peer

__all__ = ["ScoutClient", "parse_peer"]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if isinstance(dt, datetime) else None


def _media_kind(msg) -> str:
    if getattr(msg, "action", None):
        return "service"
    if msg.poll:
        return "poll"
    if msg.sticker:
        return "sticker"
    if msg.voice:
        return "voice"
    if msg.audio:
        return "audio"
    if msg.video_note:
        return "round"
    if getattr(msg, "gif", None):
        return "gif"
    if msg.video:
        return "video"
    if msg.photo:
        return "photo"
    if msg.contact:
        return "contact"
    if msg.geo:
        return "geo"
    if msg.web_preview:
        return "web"
    if msg.file:
        return "file"
    if msg.message:
        return "text"
    return "empty"


def _fwd_label(msg) -> str | None:
    if not getattr(msg, "fwd_from", None):
        return None
    fwd = getattr(msg, "forward", None)
    chat = getattr(fwd, "chat", None) if fwd else None
    if chat is not None:
        username = getattr(chat, "username", None)
        if username:
            return f"@{username}"
        title = getattr(chat, "title", None)
        if title:
            return title
    name = getattr(msg.fwd_from, "from_name", None)
    return name or "reenviado"


def _urls_from_msg(msg) -> list[str]:
    urls = extract_urls(msg.message or "")
    try:
        for ent, txt in msg.get_entities_text():
            if isinstance(ent, MessageEntityTextUrl) and getattr(ent, "url", None):
                urls.append(ent.url)
            elif isinstance(ent, MessageEntityUrl) and txt:
                urls.append(txt if "://" in txt else f"https://{txt}")
    except Exception:
        pass
    wp = getattr(msg, "web_preview", None)
    if wp and getattr(wp, "url", None):
        urls.append(wp.url)
    out: list[str] = []
    for u in urls:
        u = (u or "").rstrip(".,);!]")
        if u and u not in out:
            out.append(u)
    return out


def _mentions_from_msg(msg) -> list[str]:
    out: list[str] = []
    try:
        for ent, txt in msg.get_entities_text():
            if isinstance(ent, MessageEntityMention) and txt:
                t = txt.lstrip("@")
                if t and t not in out:
                    out.append(t)
    except Exception:
        pass
    return out


def _reactions_count(msg) -> int:
    rx = getattr(msg, "reactions", None)
    results = getattr(rx, "results", None) if rx else None
    if not results:
        return 0
    return int(sum(getattr(r, "count", 0) or 0 for r in results))


def item_from_message(msg) -> dict[str, Any]:
    media = _media_kind(msg)
    f = msg.file
    duration = getattr(f, "duration", None) if f else None
    size = getattr(f, "size", None) if f else None
    mime = (getattr(f, "mime_type", None) or "") if f else ""
    name = getattr(f, "name", None) if f else None
    w = getattr(f, "width", None) if f else None
    h = getattr(f, "height", None) if f else None
    replies = getattr(getattr(msg, "replies", None), "replies", None)
    text = msg.message or ""
    return {
        "id": msg.id,
        "date": _iso(msg.date),
        "media": media,
        "duration": duration,
        "size": size,
        "mime": mime,
        "name": name,
        "w": w,
        "h": h,
        "urls": _urls_from_msg(msg),
        "hashtags": extract_hashtags(text),
        "mentions": _mentions_from_msg(msg),
        "views": getattr(msg, "views", None),
        "forwards": getattr(msg, "forwards", None),
        "replies": replies,
        "reactions": _reactions_count(msg),
        "grouped_id": getattr(msg, "grouped_id", None),
        "fwd": _fwd_label(msg),
        "edited": bool(getattr(msg, "edit_date", None)),
        "author": getattr(msg, "post_author", None),
    }


class ScoutClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        sess = self.settings.session_path()
        session_str = str(sess.with_suffix("") if sess.suffix == ".session" else sess)
        self.client = TelegramClient(
            session_str,
            int(self.settings.telegram_api_id),
            self.settings.telegram_api_hash,
        )

    async def connect(self) -> None:
        await self.client.connect()

    async def disconnect(self) -> None:
        await self.client.disconnect()

    async def authorized(self) -> bool:
        if not self.client.is_connected():
            await self.connect()
        return bool(await self.client.is_user_authorized())

    async def resolve(self, peer: str) -> Any:
        if peer.startswith("invite:"):
            raw = peer[7:]
            h = raw.split("joinchat/")[-1].lstrip("+")
            res = await self.client(CheckChatInviteRequest(h))
            chat = getattr(res, "chat", None) or getattr(res, "channel", None)
            if chat is None:
                raise ValueError("invitación no unida o expirada")
            return chat
        if re.fullmatch(r"-?\d+", peer):
            return await self.client.get_entity(int(peer))
        return await self.client.get_entity(peer)

    async def _channel_meta(self, entity) -> dict[str, Any]:
        title = getattr(entity, "title", None) or getattr(entity, "first_name", "") or ""
        username = getattr(entity, "username", None)
        kind = "usuario"
        if isinstance(entity, Channel):
            kind = "canal" if entity.broadcast else "supergrupo"
        elif isinstance(entity, Chat):
            kind = "grupo"
        elif isinstance(entity, User):
            kind = "usuario"

        meta: dict[str, Any] = {
            "title": title,
            "kind": kind,
            "peer": f"@{username}" if username else str(getattr(entity, "id", "")),
            "entity_id": getattr(entity, "id", None),
            "members": getattr(entity, "participants_count", None),
            "created": _iso(getattr(entity, "date", None)),
            "verified": bool(getattr(entity, "verified", False)),
            "scam": bool(getattr(entity, "scam", False)),
            "fake": bool(getattr(entity, "fake", False)),
            "restricted": bool(getattr(entity, "restricted", False)),
            "noforwards": bool(getattr(entity, "noforwards", False)),
            "about": None,
            "linked_chat_id": None,
            "restriction": None,
        }
        reasons = getattr(entity, "restriction_reason", None) or []
        if reasons:
            texts = [getattr(r, "text", None) or str(r) for r in reasons]
            meta["restriction"] = "; ".join(t for t in texts if t)[:240]

        if isinstance(entity, Channel):
            try:
                full = await self.client(GetFullChannelRequest(entity))
                fc = full.full_chat
                meta["about"] = (getattr(fc, "about", None) or "").strip() or None
                meta["members"] = getattr(fc, "participants_count", None) or meta["members"]
                meta["linked_chat_id"] = getattr(fc, "linked_chat_id", None)
            except Exception:
                pass
        return meta

    async def _history_span(self, entity) -> dict[str, Any]:
        await asyncio.sleep(0.45)
        newest = await self.client.get_messages(entity, limit=1)
        await asyncio.sleep(0.7)
        oldest = await self.client.get_messages(entity, limit=1, reverse=True)
        n = newest[0] if newest else None
        o = oldest[0] if oldest else None
        nid = getattr(n, "id", None)
        oid = getattr(o, "id", None)
        est = None
        if nid and oid:
            est = max(1, int(nid) - int(oid) + 1)
        return {
            "newest_id": nid,
            "oldest_id": oid,
            "est_ids": est,
            "span_newest": _iso(getattr(n, "date", None)),
            "span_oldest": _iso(getattr(o, "date", None)),
        }

    async def preview(self, peer: str) -> dict[str, Any]:
        entity = await self.resolve(peer)
        await asyncio.sleep(0.35)
        meta = await self._channel_meta(entity)
        try:
            span = await self._history_span(entity)
            meta.update(span)
        except Exception:
            pass
        summary = set_paging(
            summarize([], meta),
            exhausted=False,
            max_sample=self.settings.max_all,
            continue_hint=self.settings.continue_limit,
        )
        summary["can_continue"] = True
        return {"summary": summary, "items": [], "entity_id": meta.get("entity_id")}

    async def ficha_map(
        self,
        peer: str,
        existing: list[dict],
        summary: dict,
        on_progress=None,
    ) -> dict[str, Any]:
        entity = await self.resolve(peer)
        meta = meta_from_summary(summary)
        span = await self._history_span(entity)
        meta.update(span)
        nid = int(span.get("newest_id") or 0)
        oid = int(span.get("oldest_id") or 0)
        est = int(span.get("est_ids") or 0)
        per = 280 if est > 20000 else 180
        items = list(existing)
        offsets = [0]
        if nid and oid and nid > oid:
            for frac in (0.8, 0.6, 0.4, 0.2):
                offsets.append(int(oid + (nid - oid) * frac))
        total_steps = len(offsets) + 1
        step = 0
        for offset in offsets:
            step += 1
            if on_progress:
                try:
                    await on_progress(step, total_steps)
                except Exception:
                    pass
            extra, _ = await self._collect_page(
                entity, limit=per, offset_id=offset, on_progress=None, pace="slow"
            )
            items = merge_items(items, extra)
        step += 1
        if on_progress:
            try:
                await on_progress(step, total_steps)
            except Exception:
                pass
        old: list[dict[str, Any]] = []
        async for msg in self.client.iter_messages(entity, limit=per, reverse=True, wait_time=2.2):
            old.append(item_from_message(msg))
        items = merge_items(items, old)
        out = set_paging(
            summarize(items, meta),
            exhausted=False,
            max_sample=self.settings.max_all,
            continue_hint=self.settings.continue_limit,
        )
        out["map_mode"] = True
        out["est_ids"] = est
        out["can_continue"] = True
        return {"summary": out, "items": items, "entity_id": meta.get("entity_id")}

    async def _collect_page(
        self,
        entity,
        *,
        limit: int,
        offset_id: int = 0,
        on_progress=None,
        pace: str = "normal",
    ) -> tuple[list[dict[str, Any]], bool]:
        items: list[dict[str, Any]] = []
        async for msg in iter_history_human(
            self.client,
            entity,
            limit=limit,
            offset_id=offset_id,
            on_progress=on_progress,
            **iter_kwargs(pace),
        ):
            items.append(item_from_message(msg))
        exhausted = len(items) < limit
        return items, exhausted

    async def ficha(self, peer: str, limit: int | None = None, on_progress=None, pace: str = "normal") -> dict[str, Any]:
        entity = await self.resolve(peer)
        await asyncio.sleep(0.4)
        limit = limit or self.settings.sample_limit
        meta = await self._channel_meta(entity)
        items, exhausted = await self._collect_page(
            entity, limit=limit, offset_id=0, on_progress=on_progress, pace=pace
        )
        cap = self.settings.max_all if pace == "crawl" else self.settings.max_sample
        summary = set_paging(
            summarize(items, meta),
            exhausted=exhausted,
            max_sample=cap,
            continue_hint=self.settings.continue_limit,
        )
        return {"summary": summary, "items": items, "entity_id": meta.get("entity_id")}

    async def ficha_more(
        self,
        peer: str,
        existing: list[dict],
        summary: dict,
        on_progress=None,
        take: int | None = None,
        pace: str = "normal",
        max_sample: int | None = None,
    ) -> dict[str, Any]:
        cap = int(max_sample or summary.get("max_sample") or self.settings.max_sample)
        room = max(0, cap - len(existing))
        if room <= 0:
            summary = set_paging(dict(summary), exhausted=False, max_sample=cap)
            summary["can_continue"] = False
            summary["continue_hint"] = take or self.settings.continue_limit
            return {"summary": summary, "items": existing, "entity_id": summary.get("entity_id")}
        want = take or self.settings.continue_limit
        limit = min(want, room)
        entity = await self.resolve(peer)
        extra, exhausted = await self._collect_page(
            entity,
            limit=limit,
            offset_id=oldest_msg_id(existing),
            on_progress=on_progress,
            pace=pace,
        )
        items = merge_items(existing, extra)
        meta = meta_from_summary(summary)
        summary = set_paging(
            summarize(items, meta),
            exhausted=exhausted,
            max_sample=cap,
            continue_hint=want,
        )
        return {"summary": summary, "items": items, "entity_id": meta.get("entity_id")}
