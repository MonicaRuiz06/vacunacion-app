"""Rutas de citas: reservar, mis citas, agenda, cancelar, reprogramar, llegada y cierre."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.controllers.cuentas import rol_requerido
from app.models.campana import Campana
from app.models.cita import Cita, preparar
from app.models.punto import Punto
from app.utils import ErroresFormulario

bp = Blueprint("citas", __name__)


def buscar_cita(cita_id):
    cita = Cita.buscar(cita_id)
    if cita is None:
        abort(404)
    return cita


def exigir_acceso(cita):
    """El paciente dueño o el personal del punto; si no, 403."""
    if not (cita.es_de(g.usuario) or cita.puede_operar(g.usuario)):
        abort(403)


@bp.route("/citas")
@rol_requerido()
def citas():
    preparar()
    if g.usuario.rol == "paciente":
        return render_template("citas/mis_citas.html", citas=Cita.de_paciente(g.usuario.id))
    fecha = request.args.get("fecha") or None
    punto_id = request.args.get("punto_id", type=int)
    puntos = Punto.listar() if g.usuario.rol == "administrador" else g.usuario.puntos()
    return render_template("citas/agenda.html", citas=Cita.agenda(g.usuario, fecha, punto_id),
                           puntos=puntos, filtros=request.args)


@bp.route("/citas/nueva", methods=["GET", "POST"])
@rol_requerido("paciente")
def nueva():
    preparar()
    campana = Campana.buscar(request.args.get("campana_id", type=int))
    if campana is None or campana.estado != "publicada":
        abort(404)
    estado = 200
    if request.method == "POST":
        try:
            Cita.reservar(g.usuario, campana.id, request.form.get("vacuna_id"),
                          request.form.get("franja_id"))
            flash("Cita reservada.", "exito")
            return redirect(url_for("citas.citas"), 303)
        except ValueError as error:
            flash(str(error), "error")
            estado = 409
    return render_template("citas/elegir.html", titulo="Reservar cita", campana=campana,
                           franjas=Cita.franjas_disponibles(campana), valores=request.form,
                           cita=None, errores={}), estado


@bp.route("/citas/<int:cita_id>/reprogramar", methods=["GET", "POST"])
@rol_requerido()
def reprogramar(cita_id):
    preparar()
    cita = buscar_cita(cita_id)
    exigir_acceso(cita)
    por_paciente = g.usuario.rol == "paciente"
    campana = Campana.buscar(request.values.get("campana_id", type=int) or cita.campana_id)
    if campana is None or campana.estado != "publicada":
        campana = None
    errores, estado = {}, 200
    if request.method == "POST":
        try:
            cita.reprogramar(g.usuario, request.form.get("campana_id"), request.form.get("vacuna_id"),
                             request.form.get("franja_id"), request.form.get("motivo"))
            flash("Cita reprogramada.", "exito")
            return redirect(url_for("citas.citas"), 303)
        except PermissionError:
            abort(403)
        except ErroresFormulario as error:
            errores, estado = error.errores, 400
            flash(str(error), "error")
        except ValueError as error:
            flash(str(error), "error")
            estado = 409
    valores = request.form if request.method == "POST" else {"vacuna_id": cita.vacuna_id}
    return render_template("citas/elegir.html", titulo="Reprogramar cita", cita=cita, campana=campana,
                           campanas=Campana.listar(solo_publicadas=True),
                           franjas=Cita.franjas_disponibles(campana, por_paciente) if campana else [],
                           valores=valores, errores=errores), estado


@bp.route("/citas/<int:cita_id>/cancelar", methods=["GET", "POST"])
@rol_requerido()
def cancelar(cita_id):
    cita = buscar_cita(cita_id)
    exigir_acceso(cita)
    errores, estado = {}, 200
    if request.method == "POST":
        try:
            cita.cancelar(g.usuario, request.form.get("motivo"))
            flash("Cita cancelada.", "exito")
            return redirect(url_for("citas.citas"), 303)
        except PermissionError:
            abort(403)
        except ErroresFormulario as error:
            errores, estado = error.errores, 400
            flash(str(error), "error")
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("citas.citas"), 303)
    return render_template("citas/motivo.html", cita=cita, accion="cancelar",
                           pedir_motivo=g.usuario.rol != "paciente", errores=errores), estado


@bp.route("/citas/<int:cita_id>/llegada", methods=["POST"])
@rol_requerido("administrador", "vacunador")
def llegada(cita_id):
    cita = buscar_cita(cita_id)
    try:
        cita.registrar_llegada(g.usuario)
        flash(f"Llegada registrada: {cita.paciente}.", "exito")
    except PermissionError:
        abort(403)
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("citas.citas", fecha=cita.fecha), 303)


@bp.route("/citas/<int:cita_id>/no-aplicada", methods=["GET", "POST"])
@rol_requerido("vacunador")
def no_aplicada(cita_id):
    cita = buscar_cita(cita_id)
    exigir_acceso(cita)
    errores, estado = {}, 200
    if request.method == "POST":
        try:
            cita.cerrar_sin_aplicar(g.usuario, request.form.get("motivo"))
            flash("Atención cerrada sin aplicación.", "exito")
            return redirect(url_for("citas.citas", fecha=cita.fecha), 303)
        except PermissionError:
            abort(403)
        except ErroresFormulario as error:
            errores, estado = error.errores, 400
            flash(str(error), "error")
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("citas.citas"), 303)
    return render_template("citas/motivo.html", cita=cita, accion="no_aplicada",
                           pedir_motivo=True, errores=errores), estado
