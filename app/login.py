"""Login: QR en la terminal, o código SMS a +59168947764."""
from __future__ import annotations

import argparse
import asyncio
import re
import sys

import qrcode
from telethon.errors import SessionPasswordNeededError

from app.config import ROOT, get_settings
from app.scout import ScoutClient


def normalize_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("591") and len(d) >= 11:
        return "+" + d
    if len(d) == 8:
        return "+591" + d
    if d.startswith("00"):
        return "+" + d[2:]
    return "+" + d if d else ""


def print_qr(url: str) -> None:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=1, box_size=1)
    qr.add_data(url)
    qr.make(fit=True)
    print("\nEscaneá ESTE QR con Telegram (cámara o Vincular dispositivo):\n")
    qr.print_ascii(invert=True)
    print()
    out = ROOT / "data" / "LOGIN.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(url + "\n", encoding="utf-8")


async def login_qr(client, minutes: int = 3) -> bool:
    qr = await client.qr_login()
    deadline = asyncio.get_event_loop().time() + minutes * 60
    while True:
        print_qr(qr.url)
        left = deadline - asyncio.get_event_loop().time()
        if left <= 0:
            return False
        wait = min(25.0, left)
        print(f"Si no escaneás, se refresca el QR. Quedan {int(left)}s…")
        try:
            await qr.wait(timeout=wait)
            return True
        except asyncio.TimeoutError:
            try:
                await qr.recreate()
            except Exception:
                return False


async def login_sms(client, phone: str) -> None:
    if not client.is_connected():
        await client.connect()
    phone = normalize_phone(phone)
    print(f"Mandando código de Telegram a {phone}…")
    await client.send_code_request(phone)
    print("Mirá Telegram en el celular (mensaje de Telegram, no SMS). Pegá el código acá.")
    code = input("Código: ").strip()
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        pw = input("Contraseña 2FA: ").strip()
        await client.sign_in(password=pw)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sms", action="store_true", help="saltar QR, mandar código al teléfono")
    parser.add_argument("--phone", default="", help="ej. 68947764 o +59168947764")
    args = parser.parse_args()

    settings = get_settings()
    phone = args.phone or getattr(settings, "telegram_phone", "") or "68947764"

    scout = ScoutClient()
    await scout.connect()
    if await scout.client.is_user_authorized():
        me = await scout.client.get_me()
        print(f"Ya autorizada. user_id={me.id}")
        await scout.disconnect()
        return

    print("Pará el bot: docker compose stop scout")
    ok = False
    if not args.sms:
        try:
            ok = await login_qr(scout.client, minutes=3)
        except Exception as e:
            print(f"QR falló ({type(e).__name__}). Paso a código.")
            ok = False

    if not ok:
        try:
            await scout.client.connect()
        except Exception:
            pass
        await login_sms(scout.client, phone)

    me = await scout.client.get_me()
    print(f"Login OK user_id={me.id}")
    (ROOT / "data" / "LOGIN.txt").write_text(f"OK user_id={me.id}\n", encoding="utf-8")
    await scout.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
