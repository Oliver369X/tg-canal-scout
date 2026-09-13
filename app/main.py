from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

from app.bot import build_application, resume_saved_jobs, scout
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_SECRET_SESSION = Path("/etc/secrets/telegram.session")
_SECRET_SESSION_B64 = Path("/etc/secrets/telegram.session.b64")


def _hydrate_session(dest: Path) -> None:
    """Copia la sesión de Render secret files al disco persistente si aún no existe."""
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _SECRET_SESSION.exists() and _SECRET_SESSION.stat().st_size > 0:
        dest.write_bytes(_SECRET_SESSION.read_bytes())
        logging.info("session copiada desde /etc/secrets/telegram.session")
        return
    if _SECRET_SESSION_B64.exists():
        dest.write_bytes(base64.b64decode(_SECRET_SESSION_B64.read_text().strip()))
        logging.info("session copiada desde /etc/secrets/telegram.session.b64")


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "canal-scout"})


async def _start_health() -> web.AppRunner:
    port = int(os.environ.get("PORT", "10000"))
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logging.info("health http 0.0.0.0:%s", port)
    return runner


async def _boot() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        print("Falta TELEGRAM_BOT_TOKEN", file=sys.stderr)
        sys.exit(1)
    _hydrate_session(settings.session_path())
    health = await _start_health()
    await scout.connect()
    ok = await scout.authorized()
    logging.info("telethon_authorized=%s", ok)
    app = build_application()
    await app.initialize()
    await app.start()
    logging.info("bot polling")
    try:
        await app.updater.start_polling(drop_pending_updates=True)
        await resume_saved_jobs(app)
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await scout.disconnect()
        await health.cleanup()


def main() -> None:
    asyncio.run(_boot())


if __name__ == "__main__":
    asyncio.run(_boot())
