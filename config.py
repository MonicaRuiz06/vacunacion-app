"""Configuración de Flask y de la base de datos SQLite."""

import os
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")

# Carga los secretos y el correo desde .env (ignorado por Git; ver .env.example).
# Las variables que ya existan en el entorno no se reemplazan.
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    # "or": un valor vacío en .env cuenta como no definido.
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-change-me"
    DATABASE = os.environ.get(
        "DATABASE_PATH", os.path.join(INSTANCE_DIR, "vacunacion.db")
    )
    # La sesión dura 8 horas; la cookie no es accesible desde JavaScript.
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_SAMESITE = "Lax"
    # Correo (opcional). Sin MAIL_SERVER no se envían correos; en modo debug
    # se muestran en la consola. Las credenciales van solo en variables de entorno.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or 587)
    MAIL_USE_TLS = (os.environ.get("MAIL_USE_TLS") or "1") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_FROM = os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USERNAME")
