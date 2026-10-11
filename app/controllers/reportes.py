"""Rutas de consultas: historial, PDF académico, panel y CSV (RF-31–35)."""

from flask import Blueprint, Response, abort, g, render_template, request

from app.controllers.cuentas import rol_requerido
from app.models.campana import Campana
from app.models.cita import preparar
from app.models.paciente import Paciente
from app.models.punto import Punto
from app.models.reporte import (
    a_csv,
    datos_paciente,
    historial,
    historial_pdf,
    leer_filtros,
    panel as datos_panel,
    puede_ver_historial,
    reporte_csv,
)
from app.utils import ahora

bp = Blueprint("reportes", __name__)


def sin_cache(respuesta):
    """Las descargas con datos personales no se guardan en cachés."""
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@bp.route("/historial")
@rol_requerido("paciente")
def mi_historial():
    paciente = Paciente.buscar_por_usuario(g.usuario.id)
    return render_template("reportes/historial.html", datos=datos_paciente(paciente.id),
                           filas=historial(paciente.id), propio=True)


@bp.route("/historial.pdf")
@rol_requerido("paciente")
def mi_historial_pdf():
    paciente = Paciente.buscar_por_usuario(g.usuario.id)
    contenido = historial_pdf(datos_paciente(paciente.id), historial(paciente.id),
                              ahora().strftime("%Y-%m-%d %H:%M"))
    return sin_cache(Response(contenido, mimetype="application/pdf", headers={
        "Content-Disposition": "attachment; filename=historial-vacunacion.pdf"}))


@bp.route("/pacientes/<int:paciente_id>/historial")
@rol_requerido("administrador", "vacunador")
def historial_paciente(paciente_id):
    preparar()
    datos = datos_paciente(paciente_id)
    if datos is None:
        abort(404)
    if not puede_ver_historial(g.usuario, paciente_id):
        abort(403)
    return render_template("reportes/historial.html", datos=datos, filas=historial(paciente_id),
                           propio=False)


@bp.route("/panel")
@rol_requerido("administrador")
def panel():
    preparar()
    filtros = leer_filtros(request.args, fecha_por_defecto=ahora().date().isoformat())
    return render_template("reportes/panel.html", datos=datos_panel(filtros), filtros=filtros,
                           campanas=Campana.listar(), puntos=Punto.listar())


@bp.route("/reportes/<tipo>.csv")
@rol_requerido("administrador")
def exportar(tipo):
    preparar()
    reporte = reporte_csv(tipo, leer_filtros(request.args))
    if reporte is None:
        abort(404)
    encabezados, filas = reporte
    return sin_cache(Response(a_csv(encabezados, filas), mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename={tipo}.csv"}))
