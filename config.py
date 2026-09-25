"""Configuración de Flask y de la base de datos SQLite."""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    DATABASE = os.environ.get(
        "DATABASE_PATH", os.path.join(INSTANCE_DIR, "vacunacion.db")
    )

