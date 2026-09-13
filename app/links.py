from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

import aiohttp
from telethon.errors import InviteHashExpiredError, InviteHashInvalidError
from telethon.tl.functions.messages import CheckChatInviteRequest

TME_INVITE = ("joinchat/", "+")


def _invite_hash(url: str) -> str | None:
    p = urlparse(url)
    host = (p.netloc or "").lower()
    if host not in {"t.me", "telegram.me", "telegram.dog"}:
        return None
    path = p.path.lstrip("/")
    if path.lower().startswith("joinchat/"):
        return path.split("/", 1)[-1]
    if path.startswith("+"):
        return path[1:]
    return None


async def check_http(session: aiohttp.ClientSession, url: str, timeout: int) -> dict[str, Any]:
    try:
        async with session.head(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            return {"url": url, "kind": "http", "ok": 200 <= r.status < 400, "status": r.status}
    except aiohttp.ClientResponseError as e:
        return {"url": url, "kind": "http", "ok": False, "status": e.status}
    except Exception as e:
        try:
            async with session.get(
                url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as r:
                return {"url": url, "kind": "http", "ok": 200 <= r.status < 400, "status": r.status}
        except Exception:
            return {"url": url, "kind": "http", "ok": False, "status": type(e).__name__}


async def check_urls(client, urls: list[str], timeout: int = 8) -> list[dict[str, Any]]:
    seen: list[str] = []
    for u in urls:
        if u not in seen:
            seen.append(u)
    results: list[dict[str, Any]] = []
    http_urls: list[str] = []

    for url in seen[:80]:
        h = _invite_hash(url)
        if h:
            try:
                await client(CheckChatInviteRequest(h))
                results.append({"url": url, "kind": "invite", "ok": True, "status": "activo"})
            except InviteHashExpiredError:
                results.append({"url": url, "kind": "invite", "ok": False, "status": "expirado"})
            except InviteHashInvalidError:
                results.append({"url": url, "kind": "invite", "ok": False, "status": "invalido"})
            except Exception as e:
                results.append({"url": url, "kind": "invite", "ok": False, "status": type(e).__name__})
        else:
            http_urls.append(url)

    connector = aiohttp.TCPConnector(limit=8)
    async with aiohttp.ClientSession(connector=connector, headers={"User-Agent": "tg-canal-scout/1.0"}) as session:
        chunk_results = await asyncio.gather(*[check_http(session, u, timeout) for u in http_urls[:40]])
        results.extend(chunk_results)
    return results
