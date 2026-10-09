"""Configuración de Flask y de la base de datos SQLite."""

import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    DATABASE = os.environ.get(
        "DATABASE_PATH", os.path.join(INSTANCE_DIR, "vacunacion.db")
    )
    # La sesión dura 8 horas; la cookie no es accesible desde JavaScript.
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_SAMESITE = "Lax"
