"""Configuración de Flask y de la base de datos SQLite."""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development").lower()
    SECRET_KEY = os.environ.get("SECRET_KEY")
    # Cookies Secure solo se envían por HTTPS. En desarrollo local se usa HTTP.
    SESSION_COOKIE_SECURE = APP_ENV == "production"
    # Cantidad de proxies inversos de confianza que agregan X-Forwarded-*.
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))
    DATABASE = os.environ.get(
        "DATABASE_PATH", os.path.join(INSTANCE_DIR, "vacunacion.db")
    )

