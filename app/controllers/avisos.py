"""Rutas de avisos: avisos propios y reintento de correos fallidos."""

from flask import Blueprint, abort, flash, g, redirect, render_template, url_for

from app.controllers.cuentas import rol_requerido
from app.models.notificacion import Notificacion

bp = Blueprint("avisos", __name__)


@bp.route("/avisos")
@rol_requerido()
def avisos():
    lista = Notificacion.de_usuario(g.usuario.id)
    Notificacion.marcar_leidos(g.usuario.id)
    return render_template("avisos/lista.html", avisos=lista)


@bp.route("/avisos/fallidos")
@rol_requerido("administrador", "vacunador")
def fallidos():
    return render_template("avisos/fallidos.html", fallidos=Notificacion.fallidos(g.usuario))


@bp.route("/avisos/<int:aviso_id>/reintentar", methods=["POST"])
@rol_requerido("administrador", "vacunador")
def reintentar(aviso_id):
    aviso = Notificacion.buscar(aviso_id)
    if aviso is None:
        abort(404)
    try:
        aviso.reintentar(g.usuario)
    except PermissionError:
        abort(403)
    except ValueError as error:
        flash(str(error), "info")
        return redirect(url_for("avisos.fallidos"), 303)
    if aviso.correo_estado == "enviado":
        flash("Correo enviado.", "exito")
    else:
        flash("El correo volvió a fallar. Puedes intentarlo más tarde.", "error")
    return redirect(url_for("avisos.fallidos"), 303)
