"""CORS helper shared across all vite-fastapi-sqlite apps."""

from __future__ import annotations

import os


def allowed_origins() -> list[str]:
    """Read CORS_ORIGINS from env, fall back to Vite dev server defaults."""
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5184,http://127.0.0.1:5184")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
