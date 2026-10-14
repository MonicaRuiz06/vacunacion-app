"""Configuración de Flask y de la base de datos SQLite."""

import os
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")

# Carga secretos y correo desde .env; las variables del entorno tienen prioridad.
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development").lower()
    SECRET_KEY = os.environ.get("SECRET_KEY")
    DATABASE = os.environ.get(
        "DATABASE_PATH", os.path.join(INSTANCE_DIR, "vacunacion.db")
    )

    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = APP_ENV == "production"

    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))

    # Correo opcional. Las credenciales se leen del entorno o de .env.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or 587)
    MAIL_USE_TLS = (os.environ.get("MAIL_USE_TLS") or "1") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_FROM = os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USERNAME")