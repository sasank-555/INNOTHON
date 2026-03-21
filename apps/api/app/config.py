from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "INNOTHON API"
    jwt_secret: str = os.getenv("INNOTHON_JWT_SECRET", "change-me-in-production")
    jwt_algorithm: str = "HS256"
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("INNOTHON_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        if origin.strip()
    )
    database_path: str = os.getenv("INNOTHON_DB_PATH", "apps/api/data/innothon.db")


settings = Settings()
