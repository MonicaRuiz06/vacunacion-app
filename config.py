"""
Configuración de la aplicación.
"""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
DATABASE_PATH = os.path.join(INSTANCE_DIR, "vacunacion.db")

class Config:
    SECRET_KEY = "clave-desarrollo"
    DATABASE = DATABASE_PATH


