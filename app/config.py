from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    media_dir: str
    page_size: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    page_size_raw = os.getenv("PAGE_SIZE", "10")
    page_size = int(page_size_raw) if page_size_raw.isdigit() else 10

    return Settings(
        app_name=os.getenv("APP_NAME", "Employee Registry"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./employees.db"),
        media_dir=os.getenv("MEDIA_DIR", "media"),
        page_size=max(page_size, 1),
    )
