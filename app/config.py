from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        extra="ignore",
        populate_by_name=True,
    )

    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_session_path: str = "data/telegram.session"
    telegram_phone: str = "68947764"
    allowed_user_id: str = ""
    sample_limit: int = 300
    continue_limit: int = 300
    max_sample: int = 4000
    max_all: int = 250000
    index_page: int = 100
    http_timeout: int = 8
    page_min: int = 18
    page_max: int = 42
    wait_min: float = 1.15
    wait_max: float = 2.8

    def session_path(self) -> Path:
        p = Path(self.telegram_session_path)
        if not p.is_absolute():
            p = ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def allowed_ids(self) -> set[int]:
        raw = (self.allowed_user_id or self.telegram_chat_id or "").strip()
        if not raw:
            return set()
        out: set[int] = set()
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if part:
                out.add(int(part))
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
