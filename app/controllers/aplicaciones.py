"""Rutas de aplicaciones registradas: listado, corregir, anular y rectificar."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.controllers.cuentas import rol_requerido
from app.models.dosis import DosisAplicada
from app.utils import ErroresFormulario

bp = Blueprint("aplicaciones", __name__)


def buscar_dosis(dosis_id):
    dosis = DosisAplicada.buscar(dosis_id)
    if dosis is None:
        abort(404)
    return dosis


def ejecutar(operacion, plantilla, dosis, mensaje, **contexto):
    """Corre la operación de un formulario POST y decide la respuesta.

    Éxito: 303 al listado. Campo inválido: 400. Regla de negocio: 409.
    Sin permiso: 403. En GET solo muestra el formulario.
    """
    errores, estado = {}, 200
    if request.method == "POST":
        try:
            operacion()
            flash(mensaje, "exito")
            return redirect(url_for("aplicaciones.listado"), 303)
        except PermissionError:
            abort(403)
        except ErroresFormulario as error:
            errores, estado = error.errores, 400
            flash(str(error), "error")
        except ValueError as error:
            flash(str(error), "error")
            estado = 409
    return render_template(plantilla, dosis=dosis, errores=errores,
                           valores=request.form if request.method == "POST" else vars(dosis),
                           **contexto), estado


@bp.route("/aplicaciones")
@rol_requerido("administrador", "vacunador")
def listado():
    return render_template("aplicaciones/lista.html", aplicaciones=DosisAplicada.listar(g.usuario))


@bp.route("/aplicaciones/<int:dosis_id>/corregir", methods=["GET", "POST"])
@rol_requerido("administrador", "vacunador")
def corregir(dosis_id):
    dosis = buscar_dosis(dosis_id)
    if not dosis.puede_corregir(g.usuario):
        abort(403)
    return ejecutar(
        lambda: dosis.corregir(g.usuario, request.form.get("motivo"), request.form.get("lote_id"),
                               request.form.get("numero_dosis")),
        "aplicaciones/corregir.html", dosis, "Aplicación corregida.",
        lotes=DosisAplicada.lotes_para(dosis.punto_id, dosis.vacuna_id, dosis.fecha_aplicacion))


@bp.route("/aplicaciones/<int:dosis_id>/anular", methods=["GET", "POST"])
@rol_requerido("administrador")
def anular(dosis_id):
    dosis = buscar_dosis(dosis_id)
    return ejecutar(
        lambda: dosis.anular(g.usuario, request.form.get("motivo"),
                             request.form.get("dosis_usada") == "si"),
        "aplicaciones/anular.html", dosis, "Aplicación anulada.")


@bp.route("/aplicaciones/<int:dosis_id>/rectificar", methods=["GET", "POST"])
@rol_requerido("administrador")
def rectificar(dosis_id):
    dosis = buscar_dosis(dosis_id)
    return ejecutar(
        lambda: dosis.rectificar(g.usuario, request.form.get("cita_id"), request.form.get("lote_id"),
                                 request.form.get("numero_dosis"), request.form.get("motivo")),
        "aplicaciones/rectificar.html", dosis, "Aplicación rectificada.",
        citas=DosisAplicada.citas_para_rectificar(dosis),
        lotes=DosisAplicada.lotes_del_punto(dosis.punto_id, dosis.fecha_aplicacion))
