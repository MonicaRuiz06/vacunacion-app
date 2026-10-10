"""Rutas de campañas y franjas."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.controllers.cuentas import rol_requerido
from app.models.campana import Campana
from app.models.franja import Franja
from app.models.punto import Punto
from app.models.vacuna import Vacuna
from app.utils import ErroresFormulario

bp = Blueprint("campanas", __name__)


def respuesta(plantilla, errores, **contexto):
    """Muestra el formulario; con errores responde 400."""
    return render_template(plantilla, errores=errores, **contexto), (400 if errores else 200)


def buscar_campana(campana_id):
    """La campaña, o 404. Quien no es administrador solo ve las publicadas."""
    campana = Campana.buscar(campana_id)
    if campana is None or (g.usuario.rol != "administrador" and campana.estado != "publicada"):
        abort(404)
    return campana


# --- Campañas -----------------------------------------------------------------


@bp.route("/campanas")
@rol_requerido()
def campanas():
    Campana.finalizar_vencidas()
    solo_publicadas = g.usuario.rol != "administrador"
    return render_template("campanas/lista.html", campanas=Campana.listar(solo_publicadas))


@bp.route("/campanas/<int:campana_id>")
@rol_requerido()
def detalle(campana_id):
    Campana.finalizar_vencidas()
    return render_template("campanas/detalle.html", campana=buscar_campana(campana_id))


@bp.route("/campanas/nueva", methods=["GET", "POST"])
@bp.route("/campanas/<int:campana_id>/editar", methods=["GET", "POST"])
@rol_requerido("administrador")
def editar(campana_id=None):
    campana = Campana.buscar(campana_id) if campana_id else Campana()
    if campana is None:
        abort(404)
    errores = {}
    if request.method == "POST":
        for campo in ("nombre", "descripcion", "fecha_inicio", "fecha_fin"):
            setattr(campana, campo, request.form.get(campo))
        campana.puntos_ids = request.form.getlist("puntos")
        campana.vacunas_ids = request.form.getlist("vacunas")
        try:
            campana.guardar(g.usuario.id)
            flash("Campaña guardada.", "exito")
            return redirect(url_for("campanas.detalle", campana_id=campana.id), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
        except ValueError as error:
            errores = {"general": str(error)}
            flash(str(error), "error")
    valores = request.form if request.method == "POST" else vars(campana)
    elegidos_puntos = request.form.getlist("puntos") if request.method == "POST" else [
        str(punto_id) for punto_id in campana.puntos_ids]
    elegidos_vacunas = request.form.getlist("vacunas") if request.method == "POST" else [
        str(vacuna_id) for vacuna_id in campana.vacunas_ids]
    return respuesta("campanas/form.html", errores, campana=campana, valores=valores,
                     puntos=Punto.listar(), vacunas=Vacuna.listar(),
                     elegidos_puntos=elegidos_puntos, elegidos_vacunas=elegidos_vacunas)


@bp.route("/campanas/<int:campana_id>/<accion>", methods=["POST"])
@rol_requerido("administrador")
def cambiar_estado(campana_id, accion):
    if accion not in ("publicar", "pausar", "reanudar"):
        abort(404)
    Campana.finalizar_vencidas()
    campana = Campana.buscar(campana_id)
    if campana is None:
        abort(404)
    try:
        getattr(campana, accion)(g.usuario.id)  # campana.publicar / pausar / reanudar
        flash(f"Campaña {campana.estado}.", "exito")
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("campanas.detalle", campana_id=campana_id), 303)


# --- Franjas ------------------------------------------------------------------


@bp.route("/franjas")
@rol_requerido("administrador")
def franjas():
    punto_id = request.args.get("punto_id", type=int)
    fecha = request.args.get("fecha") or None
    return render_template("campanas/franjas.html", franjas=Franja.listar(punto_id, fecha),
                           puntos=Punto.listar(), filtros=request.args)


@bp.route("/franjas/nueva", methods=["GET", "POST"])
@rol_requerido("administrador")
def nueva_franja():
    errores = {}
    if request.method == "POST":
        franja = Franja(
            punto_id=request.form.get("punto_id"),
            fecha=request.form.get("fecha"),
            hora_inicio=request.form.get("hora_inicio"),
            hora_fin=request.form.get("hora_fin"),
            cupos=request.form.get("cupos"),
        )
        try:
            franja.guardar()
            flash("Franja creada.", "exito")
            return redirect(url_for("campanas.franjas"), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
    return respuesta("campanas/franja_form.html", errores, valores=request.form,
                     puntos=Punto.listar())


@bp.route("/franjas/<int:franja_id>/editar", methods=["GET", "POST"])
@rol_requerido("administrador")
def editar_franja(franja_id):
    franja = Franja.buscar(franja_id)
    if franja is None:
        abort(404)
    errores = {}
    if request.method == "POST":
        try:
            franja.cambiar_cupos(request.form.get("cupos"))
            flash("Cupos actualizados.", "exito")
            return redirect(url_for("campanas.franjas"), 303)
        except ValueError as error:
            errores = {"cupos": str(error)}
            flash(str(error), "error")
    return respuesta("campanas/franja_cupos.html", errores, franja=franja,
                     punto=Punto.buscar(franja.punto_id), ocupados=franja.ocupados(),
                     valores=request.form if request.method == "POST" else vars(franja))
