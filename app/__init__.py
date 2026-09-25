"""Fábrica de la aplicación Flask."""

import os

from flask import Flask, render_template

from app import db
from config import Config


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config is not None:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)

    # El esquema usa CREATE IF NOT EXISTS, así que arrancar la app crea la
    # base inicial una vez y conserva los datos en los siguientes arranques.
    with app.app_context():
        db.init_db()

    @app.route("/")
    def inicio():
        return render_template("index.html")

    from app.controllers.control_paciente import pacientes_bp
    app.register_blueprint(pacientes_bp)

    return app
