"""Fábrica de la aplicación Flask."""

import os
import secrets

from flask import Flask, g, render_template
from flask_wtf.csrf import CSRFError, CSRFProtect

from werkzeug.middleware.proxy_fix import ProxyFix
from app import db
from app.controllers import (
    aplicaciones,
    avisos,
    campanas,
    catalogos,
    citas,
    cuentas,
    general,
    inventario,
    reportes,
)
from app.models.campana import Campana
from app.models.cita import Cita
from app.models.punto import Punto
from app.utils import fecha_larga
from config import Config


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config is not None:
        app.config.update(test_config)

    if app.config["APP_ENV"] == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError("Define SECRET_KEY antes de iniciar la app en producción.")
    if not app.config.get("SECRET_KEY"):
        # Clave efímera para desarrollo; nunca se reutiliza como secreto de producción.
        app.config["SECRET_KEY"] = secrets.token_hex(32)

    proxy_count = app.config["TRUSTED_PROXY_COUNT"]
    if proxy_count > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_count,
            x_proto=proxy_count,
            x_host=proxy_count,
            x_port=proxy_count,
        )

    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    # Protege todos los formularios POST; las plantillas usan {{ csrf_token() }}.
    CSRFProtect(app)
    app.add_template_filter(fecha_larga)

    app.register_blueprint(cuentas.bp)
    app.register_blueprint(general.bp)
    app.register_blueprint(catalogos.bp)
    app.register_blueprint(campanas.bp)
    app.register_blueprint(inventario.bp)
    app.register_blueprint(avisos.bp)
    app.register_blueprint(citas.bp)
    app.register_blueprint(aplicaciones.bp)
    app.register_blueprint(reportes.bp)

    # El esquema usa CREATE IF NOT EXISTS, así que arrancar la app crea la
    # base inicial una vez y conserva los datos en los siguientes arranques.
    with app.app_context():
        db.init_db()
        # Al arrancar se cierran las citas vencidas sin llegada (RF-20).
        Cita.procesar_vencidas()

    @app.route("/")
    def inicio():
        if g.usuario and g.usuario.rol == "administrador":
            return reportes.panel()  # el panel es el inicio del administrador
        if g.usuario:
            return render_template("index.html")  # accesos según el rol
        # Portada pública con las campañas abiertas y los puntos.
        Campana.finalizar_vencidas()
        return render_template("portada.html", campanas=Campana.listar(solo_publicadas=True),
                               puntos=Punto.listar())

    # Páginas de error en español, con la plantilla común.
    @app.errorhandler(400)
    def solicitud_invalida(error):
        return render_template("error.html", mensaje="La solicitud no es válida."), 400

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
