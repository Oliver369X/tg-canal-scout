from __future__ import annotations

from typing import Any

# Rangos anchos a propósito. El sleep real se sesga (no es un metrónomo).
PACES: dict[str, dict[str, Any]] = {
    "fast": {
        "page_min": 11,
        "page_max": 41,
        "wait_min": 0.55,
        "wait_max": 2.4,
        "look_min": 1.2,
        "look_max": 5.5,
        "look_p": 0.14,
        "idle_p": 0.04,
        "idle_min": 5.0,
        "idle_max": 16.0,
    },
    "normal": {
        "page_min": 9,
        "page_max": 43,
        "wait_min": 0.8,
        "wait_max": 3.6,
        "look_min": 2.0,
        "look_max": 8.5,
        "look_p": 0.2,
        "idle_p": 0.08,
        "idle_min": 7.0,
        "idle_max": 24.0,
    },
    "slow": {
        "page_min": 7,
        "page_max": 29,
        "wait_min": 1.4,
        "wait_max": 6.2,
        "look_min": 4.0,
        "look_max": 16.0,
        "look_p": 0.28,
        "idle_p": 0.13,
        "idle_min": 12.0,
        "idle_max": 40.0,
    },
    "crawl": {
        "page_min": 6,
        "page_max": 24,
        "wait_min": 1.8,
        "wait_max": 7.5,
        "look_min": 7.0,
        "look_max": 28.0,
        "look_p": 0.34,
        "idle_p": 0.2,
        "idle_min": 18.0,
        "idle_max": 75.0,
    },
}

AMOUNT_PACE = {
    "100": "fast",
    "300": "normal",
    "1000": "slow",
    "all": "crawl",
}

WAVE_REST = {
    "fast": (0.0, 0.0),
    "normal": (1.5, 8.0),
    "slow": (6.0, 28.0),
    "crawl": (12.0, 95.0),
}

WAVE_TAKE = {
    "fast": (80, 140),
    "normal": (90, 220),
    "slow": (70, 180),
    "crawl": (60, 210),
}


def pace_for_amount(amount: str) -> str:
    return AMOUNT_PACE.get(amount, "normal")


def iter_kwargs(name: str) -> dict[str, Any]:
    p = PACES.get(name) or PACES["normal"]
    return {
        "page_min": p["page_min"],
        "page_max": p["page_max"],
        "wait_min": p["wait_min"],
        "wait_max": p["wait_max"],
        "look_min": p["look_min"],
        "look_max": p["look_max"],
        "look_p": p["look_p"],
        "idle_p": p["idle_p"],
        "idle_min": p["idle_min"],
        "idle_max": p["idle_max"],
    }


def parse_amount(raw: str) -> int | None:
    """None = traer todo (hasta tope de seguridad)."""
    if raw in {"all", "todo", "t"}:
        return None
    n = int(raw)
    if n < 1:
        raise ValueError("cantidad inválida")
    return min(n, 50_000)
