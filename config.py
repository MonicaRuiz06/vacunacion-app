"""
Configuración de la aplicación.

TODO (equipo): aquí va la configuración de Flask: SECRET_KEY, y la
ruta del archivo de base de datos SQLite (por ejemplo, algo como
instance/vacunacion.db). Revisen el documento del proyecto.
Docs para ver cómo quedó definido esto en la propuesta técnica.
"""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")

# TODO: definir aquí la(s) clase(s) de configuración (Config,
# DevelopmentConfig, etc.) según lo que el equipo decida.
