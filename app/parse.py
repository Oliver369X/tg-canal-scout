from __future__ import annotations

import re
from urllib.parse import urlparse

TME_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/([^\s<>\)\]]+)",
    re.I,
)
AT_RE = re.compile(r"(?:^|\s)@([A-Za-z0-9_]{4,})\b")
URL_RE = re.compile(r"https?://[^\s<>\)\]]+", re.I)
HASHTAG_RE = re.compile(r"(?<![\w])#([\w]{2,80})", re.UNICODE)

SKIP_FIRST = {
    "s",
    "share",
    "iv",
    "addstickers",
    "socks",
    "proxy",
    "setlanguage",
    "login",
    "boost",
}


def _clean_token(token: str) -> str:
    return token.strip().strip("/").split("?")[0].split("#")[0].rstrip(".,);!]")


def parse_peer(text: str) -> str | None:
    text = (text or "").strip()
    m = TME_RE.search(text)
    if m:
        rest = _clean_token(m.group(1))
        if rest.startswith("+") or rest.lower().startswith("joinchat/"):
            return f"invite:{rest}"
        parts = [p for p in rest.split("/") if p]
        if not parts:
            return None
        if parts[0].lower() == "c" and len(parts) >= 2 and parts[1].isdigit():
            return f"-100{parts[1]}"
        if parts[0].lower() in SKIP_FIRST:
            parts = parts[1:]
        if not parts:
            return None
        username = parts[0].lstrip("@")
        if username.lower() in {"url", "addlist"}:
            return None
        if username and re.fullmatch(r"[A-Za-z0-9_]{3,}", username):
            return username
        return None
    m = AT_RE.search(text)
    if m:
        return m.group(1)
    if re.fullmatch(r"-?\d{6,}", text):
        return text
    if re.fullmatch(r"[A-Za-z0-9_]{4,}", text):
        return text
    return None


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for raw in URL_RE.findall(text):
        u = raw.rstrip(".,);!]")
        if u not in out:
            out.append(u)
    return out


def extract_hashtags(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for tag in HASHTAG_RE.findall(text):
        t = tag.lower()
        if t not in out:
            out.append(t)
    return out


def url_domain(url: str) -> str | None:
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None
