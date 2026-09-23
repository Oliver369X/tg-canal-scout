from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.analyze import MEDIA_LABELS
from app.config import get_settings
from app.human_read import skewed_delay
from app.links import check_urls
from app.pace import WAVE_REST, WAVE_TAKE, parse_amount, pace_for_amount
from app.scout import ScoutClient, parse_peer
from app.stats_view import build_stats
from app.store import Store

store = Store()
scout = ScoutClient()
log = logging.getLogger(__name__)
_busy: set[int] = set()
_jobs: dict[int, asyncio.Task] = {}
_stop: set[int] = set()
_pulse_at: dict[int, float] = {}


def _scan_busy_id() -> int | None:
    if _jobs:
        return next(iter(_jobs))
    if _busy:
        return next(iter(_busy))
    return None


def _fin_text(summary: dict) -> str:
    n = summary.get("sampled") or 0
    if summary.get("exhausted"):
        return (
            f"Listo. Telegram no muestra más historial de este canal ({n} posts).\n"
            "No sigue buscando. Si hay pocos videos, es que en esos posts no hay."
        )
    if summary.get("can_continue"):
        return (
            f"Tanda pausada en {n} posts. Hay más atrás: tocá +100/+300/+1000 o Todo."
        )
    return f"Tanda lista: {n} posts leídos."


async def _pulse(chat_msg, ficha_id: int, text: str) -> None:
    now = time.time()
    last = _pulse_at.get(ficha_id, 0)
    if now - last < 50:
        return
    _pulse_at[ficha_id] = now
    try:
        await chat_msg.reply_text(text)
    except Exception:
        pass

FRIENDLY_ERR = {
    "UsernameNotOccupiedError": "Ese @usuario no existe en Telegram.",
    "UsernameInvalidError": "Ese nombre de canal no es válido.",
    "ChannelPrivateError": "Canal privado. La cuenta logueada tiene que estar unida.",
    "ChannelInvalidError": "No pude abrir ese canal.",
    "InviteHashExpiredError": "La invitación está vencida.",
    "InviteHashInvalidError": "La invitación no es válida.",
    "FloodWaitError": "Telegram pidió esperar. Reintentá en un rato.",
}


def _allowed(user_id: int | None) -> bool:
    ids = get_settings().allowed_ids()
    if not ids:
        return True
    return user_id in ids


async def _gate(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if _allowed(uid):
        return True
    log.info("mensaje ignorado user_id=%s", uid)
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            f"Este bot es privado. Tu Telegram id es {uid}.\n"
            "No está en la lista permitida, por eso no ves la ficha."
        )
    return False


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d")
    except Exception:
        return iso[:10]


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
    mb = n / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


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


def _ago(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return _fmt_dt(iso)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    sec = max(0, int((datetime.now(timezone.utc) - d).total_seconds()))
    if sec < 3600:
        return f"hace {max(1, sec // 60)} min"
    if sec < 86400:
        return f"hace {sec // 3600} h"
    return f"hace {sec // 86400} d ({_fmt_dt(iso)})"


def _flags(s: dict) -> str:
    bits = []
    if s.get("verified"):
        bits.append("verificado")
    if s.get("scam"):
        bits.append("marcado scam")
    if s.get("fake"):
        bits.append("marcado fake")
    if s.get("restricted"):
        bits.append("restringido")
    if s.get("noforwards"):
        bits.append("sin reenvíos")
    if s.get("linked_chat_id"):
        bits.append("tiene grupo de comentarios")
    return " · ".join(bits)


def _count(s: dict, key: str, fallback: str | None = None) -> int:
    counts = s.get("counts") or {}
    if key in counts:
        return int(counts.get(key) or 0)
    if fallback:
        return int(s.get(fallback) or 0)
    return 0


def format_ficha(summary: dict, ficha_id: int) -> str:
    s = summary
    n = int(s.get("sampled") or 0) or 1
    lines = [
        f"Ficha — {s.get('title')}",
        f"{s.get('kind')} · {s.get('peer')}",
    ]
    if s.get("members"):
        lines.append(f"Miembros: {_num(s['members'])}")
    if s.get("created"):
        lines.append(f"Creado: {_fmt_dt(s.get('created'))}")
    flags = _flags(s)
    if flags:
        lines.append(flags)
    about = (s.get("about") or "").replace("\n", " ").strip()
    if about:
        lines.append("")
        lines.append(about[:220] + ("…" if len(about) > 220 else ""))
    if s.get("restriction"):
        lines.append(f"Restricción TG: {s['restriction'][:160]}")

    lines += [
        "",
        f"Muestra: {s.get('sampled')} posts (metadatos, no se bajó media)",
        f"Ventana: {_fmt_dt(s.get('oldest'))} → {_fmt_dt(s.get('newest'))}",
        f"Último post: {_ago(s.get('newest'))}",
        f"Ritmo: {_num(s.get('posts_per_day'))} posts/día",
    ]
    if s.get("map_mode"):
        lines.append(
            f"Esto es un MAPA de épocas, no el canal entero"
            + (f" (~{_num(s.get('est_ids'))} ids)." if s.get("est_ids") else ".")
        )
    if s.get("can_continue"):
        lines.append(
            f"Hay más atrás. Seguir leyendo suma de a {s.get('continue_hint') or 300} "
            f"con pausas (tope {s.get('max_sample') or 4000})."
        )
    elif s.get("exhausted"):
        lines.append("Llegué al final del historial visible.")
    elif s.get("max_sample") and int(s.get("sampled") or 0) >= int(s.get("max_sample") or 0):
        lines.append(f"Tope de seguridad: {s.get('max_sample')} posts. Pedime si hace falta subir.")
    if s.get("peak_hour") is not None:
        lines.append(f"Hora pico (UTC): {int(s['peak_hour']):02d}h")

    mix_keys = [
        ("photo", "photos"),
        ("video", "videos"),
        ("gif", "gifs"),
        ("file", "files"),
        ("audio", "audios"),
        ("voice", "voices"),
        ("text", "texts"),
        ("web", "webs"),
        ("sticker", "stickers"),
        ("poll", "polls"),
    ]
    mix = []
    for key, fb in mix_keys:
        c = _count(s, key, fb)
        if c:
            mix.append(f"{MEDIA_LABELS.get(key, key)} {c} ({round(100 * c / n)}%)")
    lines += ["", "Contenido"]
    if mix:
        lines.extend(f"· {x}" for x in mix)
    else:
        lines.append("· (vacío en la muestra)")
    if s.get("albums"):
        lines.append(f"Álbumes: {s['albums']}")

    lines += ["", "Videos"]
    vids = _count(s, "video", "videos")
    if vids:
        lines.append(
            f"{vids} videos · largo medio {_mins(s.get('video_duration_avg'))} · "
            f"máx {_mins(s.get('video_duration_max'))}"
        )
        lines.append(f"≥10 min: {s.get('videos_ge_10min')} · total {_mins(s.get('video_seconds'))}")
        res = s.get("resolutions") or {}
        if res:
            lines.append("Res: " + " · ".join(f"{k} {v}" for k, v in res.items()))
    else:
        lines.append("Ninguno en esta muestra")

    lines += [
        "",
        f"Peso en muestra: {_mb(s.get('size_total'))} (dato del archivo, no bajado)",
        f"Más pesado: {_mb(s.get('size_max'))} · ≥100 MB: {s.get('files_ge_100mb')}",
    ]

    if s.get("views_max") or s.get("views_avg"):
        lines += [
            "",
            "Alcance (si el canal lo muestra)",
            f"Vistas med {_num(s.get('views_median'))} · prom {_num(s.get('views_avg'))} · máx {_num(s.get('views_max'))}",
        ]
        if s.get("forwards_avg") or s.get("forwards_max"):
            lines.append(f"Reenvíos prom {_num(s.get('forwards_avg'))} · máx {_num(s.get('forwards_max'))}")
        if s.get("reactions_avg"):
            lines.append(f"Reacciones prom {_num(s.get('reactions_avg'))}")

    fwd = int(s.get("forwarded") or 0)
    orig = int(s.get("original") or 0)
    lines += ["", f"Origen: {orig} propios · {fwd} reenviados"]
    top_fwd = s.get("top_fwd") or []
    if top_fwd:
        lines.append("De: " + " · ".join(f"{name} ({c})" for name, c in top_fwd[:4]))
    if s.get("edited"):
        lines.append(f"Editados: {s['edited']}")

    lines += ["", f"Links: {s.get('with_url')} posts · {s.get('unique_urls')} URLs distintas"]
    top_d = s.get("top_domains") or []
    if top_d:
        lines.append("Dominios: " + " · ".join(f"{d} ({c})" for d, c in top_d[:5]))
    tags = s.get("top_hashtags") or []
    if tags:
        lines.append("Hashtags: " + " · ".join(f"#{t} ({c})" for t, c in tags[:5]))
    ments = s.get("top_mentions") or []
    if ments:
        lines.append("Menciones: " + " · ".join(f"@{m} ({c})" for m, c in ments[:4]))

    lines += ["", f"id:{ficha_id} · los botones de abajo agregan mensajes; esto se queda"]
    return "\n".join(lines)[:3900]


def format_choice(summary: dict, ficha_id: int) -> str:
    s = summary
    lines = [
        f"Canal — {s.get('title')}",
        f"{s.get('kind')} · {s.get('peer')}",
    ]
    if s.get("members"):
        lines.append(f"Miembros: {_num(s['members'])}")
    if s.get("created"):
        lines.append(f"Creado: {_fmt_dt(s.get('created'))}")
    flags = _flags(s)
    if flags:
        lines.append(flags)
    about = (s.get("about") or "").replace("\n", " ").strip()
    if about:
        lines.append("")
        lines.append(about[:220] + ("…" if len(about) > 220 else ""))
    est = s.get("est_ids")
    if est:
        lines += [
            "",
            f"Historial estimado: ~{_num(est)} ids "
            f"({_fmt_dt(s.get('span_oldest'))} → {_fmt_dt(s.get('span_newest'))})",
        ]
        if int(est) >= 15000:
            horas = max(8, int(int(est) / 20 * 4 / 3600))
            lines.append(
                f"Canal enorme. Todo lineal puede tardar ~{horas}h o más. "
                "Mapa lee varias épocas (~2 mil posts) y no intenta los 200k de un saque."
            )
    lines += [
        "",
        "Todavía no leí el historial. Elegí cuánto traer (solo metadatos):",
        "· 100 / 300 / 1000 — tandas concretas",
        "· Mapa — varias épocas (recomendado si es enorme)",
        "· Todo — sigue atrás con pausas; si se cae Docker, se retoma",
        "",
        "La ficha se queda en el chat. /status dice si sigue vivo.",
        f"id:{ficha_id}",
    ]
    return "\n".join(lines)[:3900]


def _amount_rows(ficha_id: int, *, first: bool) -> list[list[InlineKeyboardButton]]:
    i = ficha_id
    if first:
        a, b, c = "Traer 100", "Traer 300", "Traer 1000"
    else:
        a, b, c = "+100", "+300", "+1000"
    rows = [
        [
            InlineKeyboardButton(a, callback_data=f"G:{i}:100"),
            InlineKeyboardButton(b, callback_data=f"G:{i}:300"),
        ],
        [
            InlineKeyboardButton(c, callback_data=f"G:{i}:1000"),
            InlineKeyboardButton("Todo (lento)", callback_data=f"G:{i}:all"),
        ],
        [InlineKeyboardButton("Mapa (épocas)", callback_data=f"G:{i}:map")],
    ]
    if ficha_id in _jobs:
        rows.append([InlineKeyboardButton("Parar escaneo", callback_data=f"X:{i}")])
    return rows


def choice_keyboard(ficha_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_amount_rows(ficha_id, first=True))


def keyboard(ficha_id: int, summary: dict | None = None) -> InlineKeyboardMarkup:
    i = ficha_id
    rows = [
        [
            InlineKeyboardButton("Ficha", callback_data=f"S:{i}"),
            InlineKeyboardButton("Tipos", callback_data=f"T:{i}"),
        ],
        [
            InlineKeyboardButton("Videos largos", callback_data=f"L:{i}"),
            InlineKeyboardButton("Pesados", callback_data=f"P:{i}"),
        ],
        [
            InlineKeyboardButton("Más vistos", callback_data=f"W:{i}"),
            InlineKeyboardButton("Links", callback_data=f"U:{i}"),
        ],
        [
            InlineKeyboardButton("Más viejos", callback_data=f"V:{i}"),
            InlineKeyboardButton("Reenvíos", callback_data=f"F:{i}"),
        ],
        [
            InlineKeyboardButton("Estadística", callback_data=f"E:{i}"),
            InlineKeyboardButton("Archivos", callback_data=f"A:{i}"),
        ],
    ]
    if summary and summary.get("can_continue"):
        rows.extend(_amount_rows(i, first=False))
    elif ficha_id in _jobs:
        rows.append([InlineKeyboardButton("Parar escaneo", callback_data=f"X:{i}")])
    return InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    ok = await scout.authorized()
    extra = (
        "Sesión lista: leo canales donde ya estés unido."
        if ok
        else "Sesión Telethon NO autorizada. En el PC: docker compose --profile login run --rm login"
    )
    await update.message.reply_text(
        "Canal Scout\n\n"
        "Mandame un link t.me/canal, un @usuario, o reenviá un post.\n"
        "Te muestro el canal y elegís cuánto leer: 100, 300, 1000 o todo (lento).\n"
        "Los botones agregan mensajes: lo ya visto se queda para scrollear.\n"
        "Todo usa pausas largas; baja el riesgo de flood, no lo elimina.\n"
        "Un canal a la vez. /status te dice si sigue vivo o ya terminó.\n"
        "/stats lee la última ficha guardada: duración, peso, álbumes y sello por archivo.\n\n"
        + extra
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    ok = await scout.authorized()
    lines = [
        f"Telethon autorizado: {'sí' if ok else 'no'}",
        f"Tu id: {update.effective_user.id}",
    ]
    busy = _scan_busy_id()
    if busy:
        ficha = store.get_ficha(busy, update.effective_user.id) or store.latest_ficha(
            update.effective_user.id
        )
        n = (ficha or {}).get("summary", {}).get("sampled") if ficha else "—"
        title = (ficha or {}).get("title") or busy
        lines.append(f"Escaneo en curso: sí · {title} · van {n} posts")
        lines.append("Si no habla, igual puede estar en una pausa larga. Este /status confirma que vive.")
    else:
        lines.append("Escaneo en curso: no")
    last = store.latest_ficha(update.effective_user.id)
    if last:
        s = last.get("summary") or {}
        fin = "fin del historial" if s.get("exhausted") else "se puede seguir"
        lines.append(
            f"Última ficha: {last.get('title')} · {s.get('sampled', 0)} posts · {fin}"
        )
    lines.append("Cola: un canal a la vez (misma cuenta). No paralelo.")
    lines.append("/stats abre la estadística de la última ficha.")
    await update.message.reply_text("\n".join(lines))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    ficha = store.latest_ficha(update.effective_user.id)
    if not ficha or not ficha.get("items"):
        await update.message.reply_text("Todavía no hay una ficha guardada. Mandá un canal primero.")
        return
    summary = ficha.get("summary") or {}
    await update.message.reply_text(
        f"Estadística de {ficha.get('title') or ficha.get('peer')} · {len(ficha['items'])} posts en la base."
    )
    await _send_parts(update.message, _stat_parts(ficha, "all"), int(ficha["id"]), summary)


def _peer_from_update(update: Update) -> str | None:
    msg = update.message
    if not msg:
        return None
    origin = getattr(msg, "forward_origin", None)
    chat = getattr(origin, "chat", None) if origin else None
    if chat and getattr(chat, "username", None):
        return chat.username
    if chat and getattr(chat, "id", None):
        return str(chat.id)
    sender = getattr(msg, "sender_chat", None)
    if sender and getattr(sender, "type", None) in {"channel", "supergroup"}:
        return sender.username or str(sender.id)
    return parse_peer(msg.text or msg.caption or "")


def _friendly_error(exc: Exception) -> str:
    mapped = FRIENDLY_ERR.get(type(exc).__name__)
    if mapped:
        return mapped
    return f"No pude leer eso: {type(exc).__name__}: {exc}"


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    peer = _peer_from_update(update)
    log.info("ficha pedida peer=%s", peer)
    if not peer:
        await update.message.reply_text("No vi un canal. Pegá t.me/... o reenviá un post.")
        return
    if not await scout.authorized():
        await update.message.reply_text(
            "No puedo leer canales todavía: la sesión de tu cuenta no está logueada.\n"
            "En esta PC: docker compose --profile login run --rm login"
        )
        return
    wait = await update.message.reply_text(f"Mirando {peer}… (aún no leo el historial)")
    try:
        data = await scout.preview(peer)
    except Exception as e:
        log.exception("preview falló peer=%s", peer)
        await wait.edit_text(_friendly_error(e))
        return
    ficha_id = store.save_ficha(
        update.effective_user.id,
        data["summary"]["peer"],
        data["summary"]["title"],
        data["summary"],
        data["items"],
    )
    await wait.edit_text(
        format_choice(data["summary"], ficha_id),
        reply_markup=choice_keyboard(ficha_id),
        disable_web_page_preview=True,
    )


async def _send_parts(message, parts: list[str], ficha_id: int, summary: dict) -> None:
    if not parts:
        return
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        await message.reply_text(
            part[:3900],
            disable_web_page_preview=True,
            reply_markup=keyboard(ficha_id, summary) if last else None,
        )


def _stat_parts(ficha: dict, section: str) -> list[str]:
    built = build_stats(ficha["items"], ficha.get("peer") or "", ficha.get("title") or "")
    if section == "files":
        return built["files"]
    if section == "all":
        return built["overview"] + built["files"]
    return built["overview"]


def _item_link(peer: str, msg_id: int) -> str:
    u = peer.lstrip("@")
    if u.lstrip("-").isdigit():
        cid = u[4:] if u.startswith("-100") else u
        return f"https://t.me/c/{cid}/{msg_id}"
    return f"https://t.me/{u}/{msg_id}"


async def _reply_query(
    q,
    text: str,
    ficha_id: int,
    summary: dict | None = None,
    *,
    with_keys: bool = False,
) -> None:
    msg = q.message
    if not msg:
        return
    await msg.reply_text(
        text[:3900],
        disable_web_page_preview=True,
        reply_markup=keyboard(ficha_id, summary) if with_keys else None,
    )


async def _apply_wave(
    ficha: dict,
    user_id: int,
    *,
    take: int,
    pace: str,
    max_sample: int,
    on_progress=None,
) -> dict:
    data = await scout.ficha_more(
        ficha["peer"],
        ficha["items"],
        ficha["summary"],
        on_progress=on_progress,
        take=take,
        pace=pace,
        max_sample=max_sample,
    )
    store.update_ficha(ficha["id"], user_id, data["summary"], data["items"])
    return data


async def _run_all(ficha_id: int, user_id: int, chat_id: int, bot) -> None:
    settings = get_settings()
    pace = "crawl"
    try:
        while ficha_id not in _stop:
            ficha = store.get_ficha(ficha_id, user_id)
            if not ficha:
                break
            n = len(ficha["items"])
            if ficha["summary"].get("exhausted") or n >= settings.max_all:
                await bot.send_message(
                    chat_id,
                    _fin_text(ficha["summary"]),
                )
                await bot.send_message(
                    chat_id,
                    format_ficha(ficha["summary"], ficha_id),
                    reply_markup=keyboard(ficha_id, ficha["summary"]),
                    disable_web_page_preview=True,
                )
                break
            lo, hi = WAVE_REST[pace]
            delay = skewed_delay(lo, hi) if hi > 0 else 0
            if delay > 0:
                await bot.send_message(
                    chat_id,
                    f"Sigo vivo. Van {n} posts. Pausa ~{int(delay)}s (anti-patrón), después otra tanda.",
                )
                await asyncio.sleep(delay)
            if ficha_id in _stop:
                await bot.send_message(chat_id, f"Paré. Quedaron {n} posts leídos.")
                break
            tlo, thi = WAVE_TAKE.get(pace, (90, 200))
            take = random.randint(int(tlo), int(thi))
            await bot.send_message(chat_id, f"Otra tanda de ~{take} (Todo lento).")

            class _Chat:
                async def reply_text(self, text: str) -> None:
                    await bot.send_message(chat_id, text)

            async def progress(n: int, total: int) -> None:
                await _pulse(
                    _Chat(),
                    ficha_id,
                    f"Sigo vivo. {n}/{total} de esta tanda. No terminé.",
                )

            data = await _apply_wave(
                ficha,
                user_id,
                take=take,
                pace=pace,
                max_sample=settings.max_all,
                on_progress=progress,
            )
            sampled = int(data["summary"].get("sampled") or 0)
            await bot.send_message(
                chat_id,
                f"Van {sampled} posts (todo lento). Lo de arriba se queda.",
            )
            if data["summary"].get("exhausted"):
                await bot.send_message(chat_id, _fin_text(data["summary"]))
                await bot.send_message(
                    chat_id,
                    format_ficha(data["summary"], ficha_id),
                    reply_markup=keyboard(ficha_id, data["summary"]),
                    disable_web_page_preview=True,
                )
                break
    except Exception:
        log.exception("escaneo todo falló ficha=%s", ficha_id)
        try:
            await bot.send_message(chat_id, "El escaneo largo se cortó. Podés tocar +300 o Todo de nuevo.")
        except Exception:
            pass
    finally:
        _jobs.pop(ficha_id, None)
        _stop.discard(ficha_id)
        _busy.discard(ficha_id)
        store.finish_job(ficha_id)


def _filter_text(kind: str, ficha: dict, ficha_id: int) -> str | None:
    items = ficha["items"]
    peer = ficha["peer"]
    summary = ficha.get("summary") or {}
    lines: list[str] = []

    if kind == "S":
        return format_ficha(summary, ficha_id)

    if kind == "T":
        counts = summary.get("counts") or {}
        n = int(summary.get("sampled") or 0) or 1
        lines.append("Tipos en la muestra")
        for key, c in sorted(counts.items(), key=lambda x: -x[1]):
            if c:
                lines.append(f"· {MEDIA_LABELS.get(key, key)}: {c} ({round(100 * c / n)}%)")
        mimes = summary.get("mimes") or []
        if mimes:
            lines.append("")
            lines.append("MIME")
            for mime, c in mimes:
                lines.append(f"· {mime}: {c}")
        res = summary.get("resolutions") or {}
        if res:
            lines.append("")
            lines.append("Resolución")
            for k, v in res.items():
                lines.append(f"· {k}: {v}")
        return "\n".join(lines)

    if kind == "L":
        picked = [i for i in items if i.get("media") == "video" and (i.get("duration") or 0) >= 600]
        picked.sort(key=lambda x: -(x.get("duration") or 0))
        lines.append(f"Videos ≥10 min ({len(picked)} en la muestra)")
        for i in picked[:15]:
            lines.append(f"· {_mins(i.get('duration'))} · {_mb(i.get('size'))} — {_item_link(peer, i['id'])}")
        if not picked:
            lines.append("Ninguno en esta muestra.")
        return "\n".join(lines)

    if kind == "P":
        picked = [i for i in items if (i.get("size") or 0) >= 100 * 1024 * 1024]
        picked.sort(key=lambda x: -(x.get("size") or 0))
        lines.append(f"≥100 MB ({len(picked)} en la muestra)")
        for i in picked[:15]:
            extra = _mins(i.get("duration")) if i.get("duration") else (i.get("mime") or "")
            lines.append(f"· {_mb(i.get('size'))} {extra} — {_item_link(peer, i['id'])}")
        if not picked:
            lines.append("Ninguno en esta muestra.")
        return "\n".join(lines)

    if kind == "V":
        dated = [i for i in items if i.get("date")]
        picked = sorted(dated, key=lambda x: x["date"])[:15]
        lines.append("Más viejos de lo leído hasta ahora (no necesariamente todo el canal)")
        for i in picked:
            lines.append(f"· {_fmt_dt(i.get('date'))} · {i.get('media')} — {_item_link(peer, i['id'])}")
        return "\n".join(lines)

    if kind == "W":
        picked = [i for i in items if i.get("views")]
        picked.sort(key=lambda x: -(x.get("views") or 0))
        lines.append(f"Más vistos ({len(picked)} con dato de vistas)")
        for i in picked[:15]:
            lines.append(f"· {_num(i.get('views'))} vistas — {_item_link(peer, i['id'])}")
        if not picked:
            lines.append("Este canal no muestra vistas en la muestra.")
        return "\n".join(lines)

    if kind == "F":
        picked = [i for i in items if i.get("fwd")]
        lines.append(f"Reenvíos ({len(picked)} de {len(items)})")
        src: dict[str, int] = {}
        for i in picked:
            src[i["fwd"]] = src.get(i["fwd"], 0) + 1
        for name, c in sorted(src.items(), key=lambda x: -x[1])[:8]:
            lines.append(f"· {name}: {c}")
        for i in picked[:10]:
            lines.append(f"· {i.get('fwd')} — {_item_link(peer, i['id'])}")
        if not picked:
            lines.append("Ninguno: casi todo parece original del canal.")
        return "\n".join(lines)

    return None


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.from_user:
        return
    if not _allowed(q.from_user.id):
        await q.answer("Este bot es privado.", show_alert=True)
        return
    parts = (q.data or "").split(":")
    if len(parts) < 2:
        await q.answer()
        return
    kind = parts[0]
    try:
        ficha_id = int(parts[1])
    except ValueError:
        await q.answer()
        return

    if kind == "X":
        _stop.add(ficha_id)
        job = _jobs.get(ficha_id)
        if job:
            job.cancel()
        await q.answer("Parando…")
        store.finish_job(ficha_id)
        if q.message:
            await q.message.reply_text("Escaneo largo marcado para parar. Lo ya leído se queda en el chat.")
        return

    ficha = store.get_ficha(ficha_id, q.from_user.id)
    if not ficha:
        await q.answer("Ficha vencida. Mandá el canal de nuevo.", show_alert=True)
        return

    summary = ficha.get("summary") or {}

    if kind == "G":
        amount_raw = parts[2] if len(parts) > 2 else "300"
        if _scan_busy_id() is not None:
            await q.answer("Hay un escaneo en cola/curso. Esperá o /status.", show_alert=True)
            return
        _busy.add(ficha_id)
        await q.answer()
        store.upsert_job(ficha_id, q.from_user.id, q.message.chat_id, amount_raw)

        if amount_raw == "map":
            status = await q.message.reply_text(
                f"Armando mapa de épocas de {ficha['peer']}…\n"
                "No es el canal entero; cubre recientes, medio y viejos."
            )
            try:

                async def progress(n: int, total: int) -> None:
                    try:
                        await status.edit_text(f"Mapa… ventana {n}/{total}")
                    except Exception:
                        pass
                    await _pulse(
                        q.message,
                        ficha_id,
                        f"Sigo vivo. Mapa {n}/{total}. No terminé.",
                    )

                data = await scout.ficha_map(
                    ficha["peer"], ficha["items"], summary, on_progress=progress
                )
                store.update_ficha(ficha_id, q.from_user.id, data["summary"], data["items"])
                await q.message.reply_text(
                    "Mapa listo (muestra de varias épocas, no son los 200k).\n"
                    + _fin_text({**data["summary"], "exhausted": False, "can_continue": True})
                )
                await q.message.reply_text(
                    format_ficha(data["summary"], ficha_id),
                    reply_markup=keyboard(ficha_id, data["summary"]),
                    disable_web_page_preview=True,
                )
            except Exception as e:
                log.exception("mapa falló ficha=%s", ficha_id)
                await _reply_query(q, _friendly_error(e), ficha_id, summary)
            finally:
                _busy.discard(ficha_id)
                store.finish_job(ficha_id)
            return

        try:
            amount = parse_amount(amount_raw)
        except Exception:
            _busy.discard(ficha_id)
            store.finish_job(ficha_id)
            await q.message.reply_text("Cantidad inválida.")
            return
        pace = pace_for_amount(amount_raw)
        settings = get_settings()
        cap = settings.max_all
        take = 150 if amount is None else amount
        label = "todo (primera tanda, luego sigue lento)" if amount is None else f"{take} posts"
        status = await q.message.reply_text(
            f"Traigo {label} de {ficha['peer']}.\n"
            "Pausas entre tandas. La tarjeta de arriba se queda."
        )
        try:

            async def progress(n: int, total: int) -> None:
                try:
                    await status.edit_text(
                        f"Leyendo… {n}/{total} de esta tanda ({pace})\n"
                        "Lo anterior se queda en el chat."
                    )
                except Exception:
                    pass
                await _pulse(
                    q.message,
                    ficha_id,
                    f"Sigo vivo. {n}/{total} de esta tanda. No terminé.",
                )

            data = await _apply_wave(
                ficha,
                q.from_user.id,
                take=take,
                pace=pace,
                max_sample=cap,
                on_progress=progress,
            )
            try:
                await status.edit_text(
                    f"Tanda lista: {data['summary'].get('sampled')} posts leídos. Ficha abajo."
                )
            except Exception:
                pass
            if data["summary"].get("exhausted"):
                await q.message.reply_text(_fin_text(data["summary"]))
            if (
                amount is None
                and data["summary"].get("can_continue")
                and not data["summary"].get("exhausted")
            ):
                _jobs[ficha_id] = asyncio.create_task(
                    _run_all(ficha_id, q.from_user.id, q.message.chat_id, context.bot)
                )
            await q.message.reply_text(
                format_ficha(data["summary"], ficha_id),
                reply_markup=keyboard(ficha_id, data["summary"]),
                disable_web_page_preview=True,
            )
            if ficha_id in _jobs:
                await q.message.reply_text(
                    "Sigo en segundo plano a ritmo lento (Todo). "
                    "Tocá Parar escaneo cuando alcance. El chat no borra lo anterior."
                )
        except Exception as e:
            log.exception("traer historial falló ficha=%s", ficha_id)
            await _reply_query(q, _friendly_error(e), ficha_id, summary)
        finally:
            if ficha_id not in _jobs:
                _busy.discard(ficha_id)
                store.finish_job(ficha_id)
        return

    if kind == "M":
        if ficha_id in _busy:
            await q.answer("Todavía estoy leyendo esta ficha", show_alert=True)
            return
        if not summary.get("can_continue"):
            await q.answer("No hay más historial visible, o llegamos al tope", show_alert=True)
            return
        _busy.add(ficha_id)
        await q.answer()
        status = await q.message.reply_text(
            f"Siguiendo atrás de {ficha['peer']}… tandas chicas y pausas.\n"
            "La ficha de arriba se queda en el chat."
        )
        try:

            async def progress(n: int, total: int) -> None:
                try:
                    await status.edit_text(
                        f"Siguiendo atrás… {n}/{total} de esta tanda\n"
                        "Pausas entre tandas. La ficha anterior se queda."
                    )
                except Exception:
                    pass

            data = await scout.ficha_more(
                ficha["peer"],
                ficha["items"],
                summary,
                on_progress=progress,
            )
            store.update_ficha(
                ficha_id,
                q.from_user.id,
                data["summary"],
                data["items"],
            )
            try:
                await status.edit_text(
                    f"Listo. Ahora {data['summary'].get('sampled')} posts leídos. "
                    "Ficha actualizada abajo; la anterior sigue arriba para scrollear."
                )
            except Exception:
                pass
            await q.message.reply_text(
                format_ficha(data["summary"], ficha_id),
                reply_markup=keyboard(ficha_id, data["summary"]),
                disable_web_page_preview=True,
            )
        except Exception as e:
            log.exception("seguir leyendo falló ficha=%s", ficha_id)
            await _reply_query(q, _friendly_error(e), ficha_id, summary)
        finally:
            _busy.discard(ficha_id)
        return

    if kind in {"E", "A"}:
        await q.answer()
        section = "files" if kind == "A" else "overview"
        await q.message.reply_text("Leo la base guardada. No vuelvo a escanear.")
        await _send_parts(q.message, _stat_parts(ficha, section), ficha_id, summary)
        return

    if kind == "U":
        await q.answer()
        urls: list[str] = []
        for i in ficha["items"]:
            urls.extend(i.get("urls") or [])
        if not urls:
            await _reply_query(q, "No había links en la muestra.", ficha_id, summary)
            return
        status = await q.message.reply_text(
            f"Chequeando {min(len(set(urls)), 80)} links… (la ficha se queda arriba)"
        )
        results = await check_urls(scout.client, urls, get_settings().http_timeout)
        dead = [r for r in results if not r.get("ok")]
        live = [r for r in results if r.get("ok")]
        lines = [f"Links: {len(live)} vivos · {len(dead)} muertos/sospechosos"]
        top_d = summary.get("top_domains") or []
        if top_d:
            lines.append("Dominios: " + " · ".join(f"{d} ({c})" for d, c in top_d[:5]))
        for r in dead[:12]:
            lines.append(f"· {r.get('status')} — {r['url'][:80]}")
        if not dead:
            lines.append("No vi muertos en esta pasada (puede haber falsos vivos con captcha).")
        try:
            await status.edit_text("\n".join(lines)[:3900], disable_web_page_preview=True)
        except BadRequest:
            await _reply_query(q, "\n".join(lines), ficha_id, summary)
        return

    text = _filter_text(kind, ficha, ficha_id)
    if not text:
        await q.answer()
        return
    await q.answer()
    with_keys = kind == "S"
    await _reply_query(q, text, ficha_id, summary, with_keys=with_keys)
    return


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("error en bot")
    msg = getattr(update, "effective_message", None) if update else None
    if msg:
        try:
            await msg.reply_text("Falló al procesar eso. Mandá el link otra vez.")
        except Exception:
            pass


async def resume_saved_jobs(app: Application) -> None:
    for job in store.list_running_jobs():
        fid = int(job["ficha_id"])
        if fid in _jobs:
            continue
        _busy.add(fid)
        _jobs[fid] = asyncio.create_task(
            _run_all(fid, int(job["user_id"]), int(job["chat_id"]), app.bot)
        )
        try:
            await app.bot.send_message(
                job["chat_id"],
                "Retomé un escaneo que se había cortado. /status para ver si vive.",
            )
        except Exception:
            pass
        log.info("retomé job ficha=%s", fid)


def build_application() -> Application:
    settings = get_settings()
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    return app
