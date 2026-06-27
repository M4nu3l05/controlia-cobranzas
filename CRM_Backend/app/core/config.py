from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CRM_Backend"
    app_env: str = "development"
    app_debug: bool = True

    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 480

    cors_origins: List[str] = []

    first_admin_email: str = "admin@controlia.cl"
    first_admin_username: str = "Administrador"
    first_admin_password: str = "Admin1234"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_production_safety(self):
        if self.app_env.strip().lower() != "production":
            return self
        if self.app_debug:
            raise ValueError("APP_DEBUG debe ser false en producción.")
        if len(self.jwt_secret_key.strip()) < 32 or "cambia_esto" in self.jwt_secret_key.lower():
            raise ValueError("JWT_SECRET_KEY debe ser una clave productiva de al menos 32 caracteres.")
        if self.first_admin_password == "Admin1234" or len(self.first_admin_password) < 12:
            raise ValueError("FIRST_ADMIN_PASSWORD productiva debe tener al menos 12 caracteres y no usar el valor inicial.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
