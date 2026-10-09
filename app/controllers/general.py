"""Rutas comunes a todos los usuarios: preferencia de tema claro/noche."""

from flask import Blueprint, abort, redirect, request

bp = Blueprint("general", __name__)

TEMAS = ("claro", "oscuro")


@bp.app_context_processor
def tema_actual():
    """Pasa a todas las plantillas el tema guardado, o "sistema" si no hay."""
    tema = request.cookies.get("tema")
    return {"tema": tema if tema in TEMAS else "sistema"}


def ruta_interna(destino):
    """Solo permite volver a una página de esta aplicación."""
    if destino and destino.startswith("/") and not destino.startswith("//"):
        return destino
    return "/"


@bp.route("/tema", methods=["POST"])
def cambiar_tema():
    tema = request.form.get("tema")
    if tema not in TEMAS + ("sistema",):
        abort(400)
    respuesta = redirect(ruta_interna(request.form.get("volver")), 303)
    if tema == "sistema":
        respuesta.delete_cookie("tema")
    else:
        # Solo es una preferencia visual: no guarda datos de la cuenta.
        respuesta.set_cookie("tema", tema, max_age=365 * 24 * 3600, httponly=True,
                             samesite="Lax")
    return respuesta
