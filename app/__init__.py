"""Fábrica de la aplicación Flask."""

import os

from flask import Flask, render_template
from flask_wtf.csrf import CSRFError, CSRFProtect

from app import db
from app.controllers import cuentas
from config import Config


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config is not None:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    # Protege todos los formularios POST; las plantillas usan {{ csrf_token() }}.
    CSRFProtect(app)

    app.register_blueprint(cuentas.bp)

    # El esquema usa CREATE IF NOT EXISTS, así que arrancar la app crea la
    # base inicial una vez y conserva los datos en los siguientes arranques.
    with app.app_context():
        db.init_db()

    @app.route("/")
    def inicio():
        return render_template("index.html")

    # Páginas de error en español, con la plantilla común.
    @app.errorhandler(403)
    def sin_permiso(error):
        return render_template("error.html", mensaje="No tienes permiso para esta acción."), 403

    @app.errorhandler(404)
    def no_encontrada(error):
        return render_template("error.html", mensaje="Página no encontrada."), 404

    @app.errorhandler(CSRFError)
    def formulario_vencido(error):
        mensaje = "El formulario venció o no es válido. Recarga la página e inténtalo de nuevo."
        return render_template("error.html", mensaje=mensaje), 400

    return app
