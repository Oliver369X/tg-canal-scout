from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from app.bot import build_application, resume_saved_jobs, scout
from app.config import get_settings
from app.report import deep_stats, list_saved

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_SECRET_SESSION = Path("/etc/secrets/telegram.session")
_SECRET_SESSION_B64 = Path("/etc/secrets/telegram.session.b64")
_qr: dict = {"url": None, "waiting": False, "done": False, "error": ""}


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


def _login_token() -> str:
    return (os.environ.get("LOGIN_TOKEN") or "").strip()


def _html(body: str, refresh: int | None = None) -> web.Response:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">{meta}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canal Scout — Telegram</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem;text-align:center;color:#111}}
img{{width:280px;height:280px;background:#fff;padding:8px;border-radius:12px}}
p{{line-height:1.45}}
</style></head><body>{body}</body></html>"""
    return web.Response(text=html, content_type="text/html")


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "canal-scout"})


async def _qr_loop() -> None:
    _qr["waiting"] = True
    try:
        if await scout.authorized():
            _qr["done"] = True
            return
        qr = await scout.client.qr_login()
        deadline = asyncio.get_event_loop().time() + 180
        while True:
            _qr["url"] = qr.url
            left = deadline - asyncio.get_event_loop().time()
            if left <= 0:
                _qr["error"] = "Se venció el QR. Recargá la página."
                return
            try:
                await qr.wait(timeout=min(20.0, left))
                _qr["done"] = True
                _qr["url"] = None
                logging.info("telegram qr login ok")
                return
            except asyncio.TimeoutError:
                try:
                    await qr.recreate()
                except Exception as exc:
                    _qr["error"] = str(exc)
                    return
    except Exception as exc:
        _qr["error"] = str(exc)
        logging.exception("qr login")
    finally:
        _qr["waiting"] = False


async def _login_page(request: web.Request) -> web.Response:
    token = _login_token()
    if not token or request.match_info.get("token") != token:
        raise web.HTTPNotFound()
    if await scout.authorized():
        _qr["done"] = True
        return _html(
            "<h1>Listo</h1><p>Render ya tiene tu Telegram. No hace falta QR.</p>"
            "<p>Andá al bot y mandá <b>/start</b>.</p>"
        )
    if _qr["done"]:
        return _html("<h1>Listo</h1><p>Telegram quedó vinculado. Mandá /start al bot.</p>")
    if _qr["error"]:
        return _html(f"<h1>Error</h1><p>{_qr['error']}</p><p>Recargá para reintentar.</p>", 8)
    if not _qr["waiting"] and not _qr["url"]:
        asyncio.create_task(_qr_loop())
    if not _qr["url"]:
        return _html("<h1>Preparando QR…</h1><p>Esperá unos segundos.</p>", 2)
    src = "https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=" + quote(_qr["url"], safe="")
    return _html(
        "<h1>Escaneá este QR</h1>"
        "<p>En el celular: Telegram → <b>Ajustes → Dispositivos → Vincular dispositivo</b>, "
        "o la cámara de Telegram.</p>"
        f'<p><img alt="QR Telegram" src="{src}"></p>'
        "<p>Esta página se refresca sola. No lo escanees en el dashboard de Render.</p>",
        6,
    )


def _check_token(request: web.Request) -> None:
    token = _login_token()
    if not token or request.match_info.get("token") != token:
        raise web.HTTPNotFound()


async def _report(request: web.Request) -> web.Response:
    _check_token(request)
    ficha_raw = request.query.get("ficha")
    if ficha_raw:
        return web.json_response(deep_stats(int(ficha_raw)))
    return web.json_response(list_saved())


async def _start_http() -> web.AppRunner:
    port = int(os.environ.get("PORT", "10000"))
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    app.router.add_get("/login/{token}", _login_page)
    app.router.add_get("/report/{token}", _report)
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
    http = await _start_http()
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
        await http.cleanup()


def main() -> None:
    asyncio.run(_boot())


if __name__ == "__main__":
    asyncio.run(_boot())
