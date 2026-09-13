from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from telethon.errors import FloodWaitError

Progress = Callable[[int, int], Awaitable[None]] | None


def skewed_delay(lo: float, hi: float) -> float:
    """Pausa irregular: la mayoría cerca del rango, a veces corto, a veces se queda."""
    if hi <= 0:
        return 0.0
    lo = max(0.0, float(lo))
    hi = max(lo, float(hi))
    roll = random.random()
    if roll < 0.10:
        return random.uniform(max(0.12, lo * 0.25), max(lo, lo * 0.9))
    if roll < 0.18:
        return random.uniform(hi, hi * random.uniform(1.35, 3.1))
    warp = random.random() ** random.uniform(0.45, 2.2)
    return lo + warp * (hi - lo)


async def human_sleep(lo: float, hi: float) -> None:
    delay = skewed_delay(lo, hi)
    if delay > 0:
        await asyncio.sleep(delay)


def random_page(page_min: int, page_max: int, remaining: int) -> int:
    lo = max(1, int(page_min))
    hi = max(lo, int(page_max))
    roll = random.random()
    if roll < 0.12:
        n = random.randint(lo, max(lo, (lo + hi) // 3))
    elif roll < 0.22:
        n = random.randint(max(lo, hi - 6), hi)
    else:
        n = int(random.triangular(lo, hi, (lo + hi) / 2))
    return max(1, min(n, remaining, 100))


async def iter_history_human(
    client,
    entity,
    *,
    limit: int,
    offset_id: int = 0,
    page_min: int = 18,
    page_max: int = 42,
    wait_min: float = 1.15,
    wait_max: float = 2.8,
    look_every: tuple[int, int] = (4, 6),
    look_min: float = 2.4,
    look_max: float = 5.2,
    look_p: float = 0.18,
    idle_p: float = 0.07,
    idle_min: float = 8.0,
    idle_max: float = 28.0,
    warmup_min: float = 0.35,
    warmup_max: float = 1.05,
    on_progress: Progress = None,
):
    """Lee historial en tandas chicas, con ritmos irregulares. No marca leído ni escribe."""
    remaining = max(0, int(limit))
    offset = int(offset_id or 0)
    batches = 0
    got = 0

    if warmup_max > 0:
        await human_sleep(warmup_min, warmup_max)

    while remaining > 0:
        page = random_page(page_min, page_max, remaining)
        if batches > 0 and wait_max > 0:
            await human_sleep(wait_min, wait_max)
            if look_max > 0 and random.random() < look_p:
                await human_sleep(look_min, look_max)
            if idle_max > 0 and random.random() < idle_p:
                await human_sleep(idle_min, idle_max)
        try:
            chunk = await client.get_messages(entity, limit=page, offset_id=offset)
        except FloodWaitError as e:
            wait = int(getattr(e, "seconds", 5) or 5) + skewed_delay(2.5, 9.0)
            await asyncio.sleep(wait)
            continue
        if not chunk:
            return
        for msg in chunk:
            yield msg
            got += 1
        offset = chunk[-1].id
        remaining -= len(chunk)
        batches += 1
        if on_progress:
            try:
                await on_progress(got, limit)
            except Exception:
                pass
        if len(chunk) < page:
            return
