"""Rutas de catálogos del administrador: puntos, vacunas y lotes."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.controllers.cuentas import rol_requerido
from app.models.lote import Lote
from app.models.punto import Punto
from app.models.vacuna import Vacuna
from app.utils import ErroresFormulario

bp = Blueprint("catalogos", __name__)

CAMPOS_PUNTO = ("nombre", "direccion", "municipio", "hora_apertura", "hora_cierre", "capacidad_diaria")
CAMPOS_VACUNA = ("nombre", "fabricante", "dosis_requeridas")


def respuesta(plantilla, errores, **contexto):
    """Muestra el formulario; con errores responde 400."""
    return render_template(plantilla, errores=errores, **contexto), (400 if errores else 200)


# --- Puntos -------------------------------------------------------------------


@bp.route("/puntos")
@rol_requerido("administrador")
def puntos():
    return render_template("catalogos/puntos.html", puntos=Punto.listar())


@bp.route("/puntos/nuevo", methods=["GET", "POST"])
@bp.route("/puntos/<int:punto_id>/editar", methods=["GET", "POST"])
@rol_requerido("administrador")
def editar_punto(punto_id=None):
    punto = Punto.buscar(punto_id) if punto_id else Punto()
    if punto is None:
        abort(404)
    errores = {}
    if request.method == "POST":
        for campo in CAMPOS_PUNTO:
            setattr(punto, campo, request.form.get(campo))
        try:
            punto.guardar()
            flash("Punto guardado.", "exito")
            return redirect(url_for("catalogos.puntos"), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
        except ValueError as error:
            errores = {"hora_apertura": str(error)}
            flash(str(error), "error")
    valores = request.form if request.method == "POST" else vars(punto)
    return respuesta("catalogos/punto_form.html", errores, punto=punto, valores=valores)


# --- Vacunas ------------------------------------------------------------------


@bp.route("/vacunas")
@rol_requerido("administrador")
def vacunas():
    return render_template("catalogos/vacunas.html", vacunas=Vacuna.listar())


@bp.route("/vacunas/nueva", methods=["GET", "POST"])
@bp.route("/vacunas/<int:vacuna_id>/editar", methods=["GET", "POST"])
@rol_requerido("administrador")
def editar_vacuna(vacuna_id=None):
    vacuna = Vacuna.buscar(vacuna_id) if vacuna_id else Vacuna()
    if vacuna is None:
        abort(404)
    errores = {}
    if request.method == "POST":
        for campo in CAMPOS_VACUNA:
            setattr(vacuna, campo, request.form.get(campo))
        try:
            vacuna.guardar()
            flash("Vacuna guardada.", "exito")
            return redirect(url_for("catalogos.vacunas"), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
    valores = request.form if request.method == "POST" else vars(vacuna)
    return respuesta("catalogos/vacuna_form.html", errores, vacuna=vacuna, valores=valores)


# --- Lotes --------------------------------------------------------------------


@bp.route("/lotes")
@rol_requerido("administrador")
def lotes():
    return render_template("catalogos/lotes.html", lotes=Lote.listar())


@bp.route("/lotes/nuevo", methods=["GET", "POST"])
@rol_requerido("administrador")
def nuevo_lote():
    errores = {}
    if request.method == "POST":
        lote = Lote(
            vacuna_id=request.form.get("vacuna_id"),
            codigo=request.form.get("codigo"),
            fecha_vencimiento=request.form.get("fecha_vencimiento"),
        )
        try:
            lote.guardar()
            flash("Lote registrado.", "exito")
            return redirect(url_for("catalogos.lotes"), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
    return respuesta("catalogos/lote_form.html", errores, valores=request.form,
                     vacunas=Vacuna.listar())
