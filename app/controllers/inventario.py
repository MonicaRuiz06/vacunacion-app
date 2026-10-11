"""Rutas de inventario: saldo por lote, entradas, ajustes y movimientos."""

import secrets

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.controllers.cuentas import rol_requerido
from app.models.cita import preparar
from app.models.inventario import Inventario, registrar_entrada
from app.models.lote import Lote
from app.models.punto import Punto
from app.utils import ErroresFormulario

bp = Blueprint("inventario", __name__)


def respuesta(plantilla, errores, **contexto):
    """Muestra el formulario; con errores responde 400."""
    return render_template(plantilla, errores=errores, **contexto), (400 if errores else 200)


def clave_formulario():
    """Clave oculta del formulario: si se envía dos veces, se registra una sola."""
    return request.form.get("clave") or secrets.token_urlsafe(16)


@bp.route("/inventario")
@rol_requerido("administrador", "vacunador")
def inventario():
    preparar()
    # El vacunador solo consulta sus puntos asignados.
    puntos_ids = None
    if g.usuario.rol == "vacunador":
        puntos_ids = [punto["id"] for punto in g.usuario.puntos()]
    return render_template("inventario/inventario.html",
                           existencias=Inventario.listar(puntos_ids),
                           resumen=Inventario.resumen(puntos_ids))


@bp.route("/inventario/entrada", methods=["GET", "POST"])
@rol_requerido("administrador")
def entrada():
    errores = {}
    if request.method == "POST":
        try:
            registrar_entrada(request.form.get("punto_id"), request.form.get("lote_id"),
                              request.form.get("cantidad"), request.form.get("motivo"),
                              g.usuario.id, request.form.get("clave"))
            flash("Entrada registrada.", "exito")
            return redirect(url_for("inventario.inventario"), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
    return respuesta("inventario/entrada.html", errores, valores=request.form,
                     puntos=Punto.listar(), lotes=Lote.opciones(), clave=clave_formulario())


@bp.route("/inventario/<int:inventario_id>/ajuste", methods=["GET", "POST"])
@rol_requerido("administrador")
def ajuste(inventario_id):
    inventario = Inventario.buscar(inventario_id)
    if inventario is None:
        abort(404)
    errores = {}
    if request.method == "POST":
        try:
            inventario.ajustar(request.form.get("cantidad"), request.form.get("motivo"),
                               g.usuario.id, request.form.get("clave"))
            flash("Ajuste registrado.", "exito")
            return redirect(url_for("inventario.inventario"), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
    return respuesta("inventario/ajuste.html", errores, valores=request.form,
                     detalle=Inventario.detalle(inventario_id), clave=clave_formulario())


@bp.route("/inventario/movimientos")
@rol_requerido("administrador")
def movimientos():
    return render_template("inventario/movimientos.html", movimientos=Inventario.movimientos())
