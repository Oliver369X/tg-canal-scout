"""Ficha de un canal por CLI: python -m app.ficha CursosFacialix"""
from __future__ import annotations

import asyncio
import json
import sys

from app.parse import parse_peer
from app.scout import ScoutClient


async def main() -> None:
    raw = " ".join(sys.argv[1:]).strip() or "CursosFacialix"
    peer = parse_peer(raw) or raw.lstrip("@")
    scout = ScoutClient()
    await scout.connect()
    if not await scout.authorized():
        print("NO_AUTH")
        print("La sesión Telethon no está autorizada.")
        print("Pará el bot y corré: docker compose --profile login run --rm login")
        await scout.disconnect()
        sys.exit(2)
    data = await scout.ficha(peer)
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
    await scout.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
