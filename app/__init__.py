"""
Fábrica de la aplicación (Application Factory Pattern).

TODO (equipo): mover aquí la creación de la app Flask desde run.py,
usando una función create_app() que:
  1. Cree la instancia de Flask
  2. Cargue la configuración desde config.py
  3. Registre los blueprints de app/controllers/
  4. Inicialice la base de datos (ver app/models/)

Referencia: la explicación de la arquitectura MVC está en el
documento del proyecto.
"""

"""
Fábrica de la aplicación Flask.
"""

"""
Fábrica de la aplicación Flask.
"""

import os

from flask import Flask, render_template
from config import Config

def create_app():

  app = Flask(
    
     __name__,
     template_folder="templates",
     static_folder="static"
     )
  app.config.from_object(Config)
  os.makedirs(app.instance_path, exist_ok=True)
  @app.route("/")

  def inicio():

    return render_template("index.html")
  from app.controllers.control_paciente import pacientes_bp
  app.register_blueprint(pacientes_bp)
  return app