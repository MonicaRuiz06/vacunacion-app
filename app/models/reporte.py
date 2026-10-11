"""Consultas de reportes: historial, panel administrativo, PDF y CSV (RF-31–35).

Las aplicaciones anuladas nunca cuentan y las corregidas se muestran con su
valor actual (hay una sola fila vigente por aplicación).
"""

import csv
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.db import get_db
from app.models.campana import Campana
from app.models.cita import NOMBRES_ESTADO
from app.models.franja import ESTADOS_QUE_OCUPAN
from app.models.inventario import Inventario
from app.utils import ahora, fecha_requerida

ESTADOS_DE_ATENCION = ("reservada", "presente", "aplicada", "no_aplicada", "registro_anulado")


# --- Filtros ------------------------------------------------------------------


def leer_filtros(args, fecha_por_defecto=None):
    """Filtros de RF-34 desde la URL. Los valores inválidos se ignoran."""
    filtros = {"desde": fecha_por_defecto, "hasta": fecha_por_defecto, "campana_id": None, "punto_id": None}
    for campo in ("desde", "hasta"):
        try:
            filtros[campo] = fecha_requerida(args.get(campo))
        except ValueError:
            pass
    for campo in ("campana_id", "punto_id"):
        valor = args.get(campo, "")
        filtros[campo] = int(valor) if valor.isdigit() else None
    return filtros


def condiciones(filtros, campo_fecha, campo_campana, campo_punto):
    """Arma el WHERE de una consulta con los filtros elegidos."""
    partes, parametros = [], []
    if filtros["desde"]:
        partes.append(f"{campo_fecha} >= ?")
        parametros.append(filtros["desde"])
    if filtros["hasta"]:
        partes.append(f"{campo_fecha} <= ?")
        parametros.append(filtros["hasta"])
    if filtros["campana_id"]:
        partes.append(f"{campo_campana} = ?")
        parametros.append(filtros["campana_id"])
    if filtros["punto_id"]:
        partes.append(f"{campo_punto} = ?")
        parametros.append(filtros["punto_id"])
    return (" WHERE " + " AND ".join(partes) if partes else ""), parametros


# --- Consultas ----------------------------------------------------------------


def citas_filtradas(filtros):
    donde, parametros = condiciones(filtros, "f.fecha", "c.campana_id", "f.punto_id")
    return get_db().execute(
        "SELECT c.id, ca.nombre AS campana, u.nombre_completo AS paciente, v.nombre AS vacuna,"
        " pu.nombre AS punto, f.fecha, f.hora_inicio, f.hora_fin, c.estado"
        " FROM citas c JOIN franjas f ON f.id = c.franja_id JOIN campanas ca ON ca.id = c.campana_id"
        " JOIN pacientes p ON p.id = c.paciente_id JOIN usuarios u ON u.id = p.usuario_id"
        " JOIN vacunas v ON v.id = c.vacuna_id JOIN puntos_vacunacion pu ON pu.id = f.punto_id"
        + donde + " ORDER BY f.fecha, f.hora_inicio, c.id",
        parametros,
    ).fetchall()


def aplicaciones_filtradas(filtros):
    """Aplicaciones vigentes del período (fecha real de aplicación)."""
    donde, parametros = condiciones(filtros, "d.fecha_aplicacion", "c.campana_id", "d.punto_id")
    donde = (donde + " AND" if donde else " WHERE") + " d.estado = 'vigente'"
    return get_db().execute(
        "SELECT d.id, d.cita_id, u.nombre_completo AS paciente, v.nombre AS vacuna, d.numero_dosis,"
        " d.fecha_aplicacion, l.codigo AS lote, pu.nombre AS punto, ca.nombre AS campana"
        " FROM dosis_aplicadas d JOIN citas c ON c.id = d.cita_id JOIN campanas ca ON ca.id = c.campana_id"
        " JOIN pacientes p ON p.id = d.paciente_id JOIN usuarios u ON u.id = p.usuario_id"
        " JOIN vacunas v ON v.id = d.vacuna_id JOIN lotes l ON l.id = d.lote_id"
        " JOIN puntos_vacunacion pu ON pu.id = d.punto_id"
        + donde + " ORDER BY d.fecha_aplicacion, d.id",
        parametros,
    ).fetchall()


def puntos_del_filtro(filtros):
    """El inventario solo se filtra por punto, nunca por fecha ni campaña (RF-34)."""
    return [filtros["punto_id"]] if filtros["punto_id"] else None


def panel(filtros):
    """Datos del panel del administrador; los totales salen de las mismas consultas del detalle."""
    citas = citas_filtradas(filtros)
    aplicadas = aplicaciones_filtradas(filtros)
    por_estado = {estado: 0 for estado in NOMBRES_ESTADO}
    for cita in citas:
        por_estado[cita["estado"]] += 1
    atendibles = sum(por_estado[estado] for estado in ESTADOS_DE_ATENCION)
    puntos = puntos_del_filtro(filtros)
    return {
        "total_citas": len(citas),
        "por_estado": [(NOMBRES_ESTADO[estado], total) for estado, total in por_estado.items()],
        "presentes": por_estado["presente"],
        "aplicadas": len(aplicadas),
        "porcentaje": round(len(aplicadas) * 100 / atendibles) if atendibles else 0,
        "faltantes": [fila for fila in Inventario.resumen(puntos) if fila["faltante"]],
        "existencias": Inventario.listar(puntos),
        "campanas": resumen_campanas(filtros["campana_id"]),
        "proximas": proximas_franjas(filtros["punto_id"]),
    }


def resumen_campanas(campana_id=None):
    """Cada campaña con sus citas que ocupan cupo frente a los cupos de sus franjas."""
    marcas = ", ".join("?" for _ in ESTADOS_QUE_OCUPAN)
    resumen = []
    for campana in Campana.listar():
        if campana_id and campana.id != campana_id:
            continue
        ocupadas = get_db().execute(
            f"SELECT COUNT(*) FROM citas WHERE campana_id = ? AND estado IN ({marcas})",
            (campana.id, *ESTADOS_QUE_OCUPAN),
        ).fetchone()[0]
        cupos = sum(franja["cupos"] for franja in campana.franjas())
        resumen.append({
            "id": campana.id, "nombre": campana.nombre, "estado": campana.estado,
            "fechas": f"{campana.fecha_inicio} a {campana.fecha_fin}",
            "vacunas": ", ".join(vacuna["nombre"] for vacuna in campana.vacunas()),
            "puntos": len(campana.puntos_ids), "ocupadas": ocupadas, "cupos": cupos,
            "porcentaje": round(ocupadas * 100 / cupos) if cupos else 0,
        })
    return resumen


def proximas_franjas(punto_id=None, limite=5):
    """Próximas franjas (desde hoy) con sus cupos libres."""
    marcas = ", ".join("?" for _ in ESTADOS_QUE_OCUPAN)
    consulta = (
        "SELECT f.fecha, f.hora_inicio, p.nombre AS punto, f.cupos,"
        f" f.cupos - (SELECT COUNT(*) FROM citas c WHERE c.franja_id = f.id AND c.estado IN ({marcas}))"
        " AS libres FROM franjas f JOIN puntos_vacunacion p ON p.id = f.punto_id"
        " WHERE (f.fecha || ' ' || f.hora_fin) >= ?"
    )
    parametros = [*ESTADOS_QUE_OCUPAN, ahora().strftime("%Y-%m-%d %H:%M")]
    if punto_id:
        consulta += " AND f.punto_id = ?"
        parametros.append(punto_id)
    consulta += " ORDER BY f.fecha, f.hora_inicio LIMIT ?"
    parametros.append(limite)
    return get_db().execute(consulta, parametros).fetchall()


# --- Historial (RF-31, RF-32) -------------------------------------------------


def historial(paciente_id):
    """Aplicaciones vigentes del paciente, con su versión corregida."""
    return get_db().execute(
        "SELECT d.fecha_aplicacion, v.nombre AS vacuna, d.numero_dosis, l.codigo AS lote,"
        " p.nombre AS punto FROM dosis_aplicadas d JOIN vacunas v ON v.id = d.vacuna_id"
        " JOIN lotes l ON l.id = d.lote_id JOIN puntos_vacunacion p ON p.id = d.punto_id"
        " WHERE d.paciente_id = ? AND d.estado = 'vigente' ORDER BY d.fecha_aplicacion, v.nombre",
        (paciente_id,),
    ).fetchall()


def datos_paciente(paciente_id):
    return get_db().execute(
        "SELECT p.id, p.usuario_id, u.nombre_completo, u.tipo_documento || ' ' || u.identificacion"
        " AS documento, p.fecha_nacimiento FROM pacientes p JOIN usuarios u ON u.id = p.usuario_id"
        " WHERE p.id = ?",
        (paciente_id,),
    ).fetchone()


def puede_ver_historial(usuario, paciente_id):
    """Quién consulta el historial de un paciente (RF-31, RF-32).

    El administrador, el propio paciente, o un vacunador que lo atiende: con
    una cita actual o una atención ya realizada en un punto que hoy tiene
    asignado. Una cita cancelada o sin asistencia no da acceso.
    """
    if usuario.rol == "administrador":
        return True
    if usuario.rol == "paciente":
        fila = datos_paciente(paciente_id)
        return fila is not None and fila["usuario_id"] == usuario.id
    marcas = ", ".join("?" for _ in ESTADOS_DE_ATENCION)
    return get_db().execute(
        "SELECT 1 FROM citas c JOIN franjas f ON f.id = c.franja_id"
        " JOIN vacunador_punto vp ON vp.punto_id = f.punto_id AND vp.usuario_id = ?"
        f" WHERE c.paciente_id = ? AND c.estado IN ({marcas})",
        (usuario.id, paciente_id, *ESTADOS_DE_ATENCION),
    ).fetchone() is not None


# --- PDF (RF-33) --------------------------------------------------------------


def historial_pdf(datos, filas, emitido):
    """PDF académico con el historial vigente completo. Devuelve los bytes."""
    salida = io.BytesIO()
    documento = SimpleDocTemplate(salida, pagesize=letter, title="Historial académico de vacunación",
                                  pageCompression=0)
    estilos = getSampleStyleSheet()
    contenido = [
        Paragraph("Historial académico de vacunación", estilos["Title"]),
        # La leyenda va sola en su línea para que siempre se lea completa (RF-33).
        Paragraph("<b>Documento académico — sin validez oficial</b>", estilos["Normal"]),
        Paragraph(f"Paciente: {escape(datos['nombre_completo'])} · {escape(datos['documento'])}"
                  f" · nacimiento {datos['fecha_nacimiento']}", estilos["Normal"]),
        Paragraph(f"Emitido: {emitido} (hora de Colombia)", estilos["Normal"]),
        Spacer(1, 12),
    ]
    if filas:
        tabla = Table(
            [["Fecha", "Vacuna", "Dosis", "Lote", "Punto"]]
            + [[f["fecha_aplicacion"], f["vacuna"], str(f["numero_dosis"]), f["lote"], f["punto"]]
               for f in filas],
            repeatRows=1,  # el encabezado se repite en cada página
        )
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#004B87")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E1EC")),
        ]))
        contenido.append(tabla)
    else:
        contenido.append(Paragraph("No hay aplicaciones registradas.", estilos["Normal"]))
    contenido += [
        Spacer(1, 12),
        Paragraph("Documento académico con datos ficticios. No es un certificado oficial de vacunación.",
                  estilos["Italic"]),
    ]

    def numerar(lienzo, plantilla):
        lienzo.setFont("Helvetica", 8)
        lienzo.drawRightString(letter[0] - 72, 40, f"Página {plantilla.page}")

    documento.build(contenido, onFirstPage=numerar, onLaterPages=numerar)
    return salida.getvalue()


# --- CSV (RF-35) --------------------------------------------------------------


def seguro_para_hoja(valor):
    """Evita que una hoja de cálculo ejecute fórmulas escritas en los datos."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


def a_csv(encabezados, filas):
    """Texto CSV con BOM (Excel reconoce UTF-8) y valores neutralizados."""
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(encabezados)
    for fila in filas:
        escritor.writerow([seguro_para_hoja(valor) for valor in fila])
    return "﻿" + salida.getvalue()


def reporte_csv(tipo, filtros):
    """(encabezados, filas) del reporte pedido, o None si el tipo no existe."""
    if tipo == "citas":
        return (["Id", "Campaña", "Paciente", "Vacuna", "Punto", "Fecha", "Inicio", "Fin", "Estado"],
                [[c["id"], c["campana"], c["paciente"], c["vacuna"], c["punto"], c["fecha"],
                  c["hora_inicio"], c["hora_fin"], NOMBRES_ESTADO[c["estado"]]]
                 for c in citas_filtradas(filtros)])
    if tipo == "aplicaciones":
        return (["Id", "Cita", "Paciente", "Vacuna", "Número de dosis", "Fecha de aplicación", "Lote",
                 "Punto", "Campaña"],
                [list(fila) for fila in aplicaciones_filtradas(filtros)])
    if tipo == "inventario":
        return (["Punto", "Vacuna", "Lote", "Vence", "Saldo físico", "Estado"],
                [[f["punto"], f["vacuna"], f["lote"], f["fecha_vencimiento"], f["cantidad_disponible"],
                  "Vencido" if f["vencido"] else "Vigente"]
                 for f in Inventario.listar(puntos_del_filtro(filtros))])
    return None
