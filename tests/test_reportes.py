"""Pruebas de historial, PDF, panel y CSV (M10): RF-31–35."""

import csv
import io

import pytest

from app.models.dosis import DosisAplicada
from app.models.paciente import Paciente
from app.models.reporte import historial, historial_pdf, puede_ver_historial
from app.models.usuario import Usuario
from tests.conftest import (
    FRANJA_FECHA,
    aplicar,
    atender,
    crear_lote,
    crear_paciente,
    hora,
    ingresar,
)


def paciente_id(app, usuario_id):
    with app.app_context():
        return Paciente.buscar_por_usuario(usuario_id).id


def otro_paciente(app, numero, nombre="Pedro Ruiz"):
    return crear_paciente(app, nombre_completo=nombre, identificacion=f"50{numero}",
                          correo=f"p{numero}@example.com")


def leer_csv(respuesta):
    texto = respuesta.get_data().decode("utf-8")
    assert texto.startswith("﻿")  # BOM para que Excel lea las tildes
    return list(csv.reader(io.StringIO(texto.lstrip("﻿"))))


@pytest.fixture
def aplicada(app, esc, reloj):
    """Laura con una dosis aplicada en Campus el 2026-10-20."""
    cita_id = atender(app, esc, reloj, esc["paciente"])
    return aplicar(app, esc, cita_id)


# RF-32 — Historial del paciente


def test_rf32_historial_muestra_aplicaciones_vigentes(app, esc, aplicada):
    with app.app_context():
        filas = historial(paciente_id(app, esc["paciente"]))
    assert [(f["vacuna"], f["numero_dosis"], f["fecha_aplicacion"], f["lote"], f["punto"]) for f in filas] == [
        ("Influenza", 1, FRANJA_FECHA, "L-2041", "Punto Campus")]


def test_rf32_muestra_la_version_corregida_y_no_las_anuladas(app, esc, aplicada):
    nuevo = crear_lote(app, esc["vacuna"], codigo="L-3000", fecha_vencimiento="2027-01-31")
    with app.app_context():
        from app.models.inventario import registrar_entrada

        registrar_entrada(esc["campus"], nuevo, 5, "Entrega", esc["admin"])
        admin = Usuario.buscar(esc["admin"])
        DosisAplicada.buscar(aplicada).corregir(admin, "Lote real", lote_id=nuevo)
        assert [f["lote"] for f in historial(paciente_id(app, esc["paciente"]))] == ["L-3000"]
        DosisAplicada.buscar(aplicada).anular(admin, "Registro duplicado", dosis_usada=False)
        assert historial(paciente_id(app, esc["paciente"])) == []


def test_rf32_paciente_ve_su_historial_y_no_el_ajeno(app, client, esc, aplicada):
    otro = otro_paciente(app, 1)
    ingresar(client)
    html = client.get("/historial").get_data(as_text=True)
    assert "L-2041" in html
    assert "Influenza" in html
    assert client.get(f"/pacientes/{paciente_id(app, otro)}/historial").status_code == 403
    assert client.get(f"/pacientes/{paciente_id(app, esc['paciente'])}/historial").status_code == 403


# RF-31 — Historial durante la atención


def puede(app, usuario_id, paciente_usuario_id):
    with app.app_context():
        return puede_ver_historial(Usuario.buscar(usuario_id), paciente_id(app, paciente_usuario_id))


def test_rf31_vacunador_ve_historial_de_paciente_con_cita_en_su_punto(app, esc, reloj):
    from app.models.cita import Cita

    reloj["ahora"] = hora("2026-10-08 12:00")
    with app.app_context():
        Cita.reservar(Usuario.buscar(esc["paciente"]), esc["campana"], esc["vacuna"], esc["franja"])
    assert puede(app, esc["vacunador"], esc["paciente"])
    assert puede(app, esc["admin"], esc["paciente"])


def test_rf31_sin_relacion_o_con_cita_cancelada_no_hay_acceso(app, esc, reloj):
    from app.models.cita import Cita

    assert not puede(app, esc["vacunador"], esc["paciente"])
    with app.app_context():
        cita_id = Cita.reservar(Usuario.buscar(esc["paciente"]), esc["campana"], esc["vacuna"], esc["franja"])
        Cita.buscar(cita_id).cancelar(Usuario.buscar(esc["paciente"]))
    assert not puede(app, esc["vacunador"], esc["paciente"])


def test_rf31_atencion_previa_mientras_siga_asignado(app, esc, aplicada):
    assert puede(app, esc["vacunador"], esc["paciente"])
    with app.app_context():
        Usuario.buscar(esc["vacunador"]).asignar_puntos([esc["centro"]], esc["admin"])
    assert not puede(app, esc["vacunador"], esc["paciente"])


def test_rf31_vacunador_consulta_desde_la_agenda(app, client, esc, aplicada):
    ingresar(client, identificacion="7001")
    ruta = f"/pacientes/{paciente_id(app, esc['paciente'])}/historial"
    assert ruta in client.get(f"/citas?fecha={FRANJA_FECHA}").get_data(as_text=True)
    html = client.get(ruta).get_data(as_text=True)
    assert "Laura Gómez" in html
    assert "L-2041" in html


# RF-33 — PDF académico


def test_rf33_pdf_del_paciente_con_leyenda(app, client, esc, aplicada):
    ingresar(client)
    respuesta = client.get("/historial.pdf")
    assert respuesta.status_code == 200
    assert respuesta.mimetype == "application/pdf"
    assert "attachment" in respuesta.headers["Content-Disposition"]
    assert respuesta.headers["Cache-Control"] == "no-store"
    contenido = respuesta.get_data()
    assert contenido.startswith(b"%PDF")
    assert b"sin validez oficial" in contenido
    assert b"L-2041" in contenido


def test_rf33_pdf_sin_aplicaciones(app, client, esc):
    ingresar(client)
    contenido = client.get("/historial.pdf").get_data()
    assert b"No hay aplicaciones registradas" in contenido


def test_rf33_pdf_de_varias_paginas_repite_encabezado(app):
    filas = [{"fecha_aplicacion": "2026-10-20", "vacuna": "Influenza", "numero_dosis": 1,
              "lote": f"L-{n}", "punto": "Punto Campus"} for n in range(90)]
    datos = {"nombre_completo": "Laura Gómez", "documento": "CC 1001", "fecha_nacimiento": "2000-05-10"}
    contenido = historial_pdf(datos, filas, "2026-10-08 12:00")
    assert contenido.count(b"/Type /Page\n") + contenido.count(b"/Type /Page ") >= 2
    assert contenido.count(b"(Vacuna)") >= 2  # el encabezado de la tabla se repite


def test_rf33_solo_el_paciente_descarga_su_pdf(app, client, esc):
    ingresar(client, identificacion="9001")
    assert client.get("/historial.pdf").status_code == 403


# RF-34 — Panel administrativo


def test_rf34_inicio_del_administrador_es_el_panel(app, client, esc, aplicada):
    ingresar(client, identificacion="9001")
    html = client.get(f"/?desde={FRANJA_FECHA}&hasta={FRANJA_FECHA}").get_data(as_text=True)
    assert "Resumen de la jornada" in html
    assert "Nueva campaña" in html
    assert "Próximas franjas" in html
    assert 'name="campana_id"' in html


def test_rf34_totales_coherentes_y_anuladas_fuera(app, client, esc, aplicada, reloj):
    from app.models.cita import Cita

    reloj["ahora"] = hora("2026-10-08 12:00")
    with app.app_context():
        Cita.reservar(Usuario.buscar(otro_paciente(app, 1)), esc["campana"], esc["vacuna"], esc["franja_centro"])
    ingresar(client, identificacion="9001")
    filtros = f"desde={FRANJA_FECHA}&hasta={FRANJA_FECHA}"
    html = client.get(f"/panel?{filtros}").get_data(as_text=True)
    assert 'data-total="citas">2<' in html
    assert 'data-total="aplicadas">1<' in html
    with app.app_context():
        DosisAplicada.buscar(aplicada).anular(Usuario.buscar(esc["admin"]), "Error", dosis_usada=False)
    html = client.get(f"/panel?{filtros}").get_data(as_text=True)
    assert 'data-total="aplicadas">0<' in html


def test_rf34_filtro_de_punto_y_fecha(app, client, esc, aplicada):
    ingresar(client, identificacion="9001")
    otro_dia = client.get("/panel?desde=2026-11-01&hasta=2026-11-30").get_data(as_text=True)
    assert 'data-total="citas">0<' in otro_dia
    centro = client.get(f"/panel?desde={FRANJA_FECHA}&hasta={FRANJA_FECHA}&punto_id={esc['centro']}").get_data(as_text=True)
    assert 'data-total="citas">0<' in centro


def test_rf34_inventario_no_se_filtra_por_fecha_ni_campana(app, client, esc, aplicada):
    ingresar(client, identificacion="9001")
    html = client.get(f"/panel?desde=2026-11-01&hasta=2026-11-30&campana_id={esc['campana']}").get_data(as_text=True)
    assert "L-2041" in html  # existencias actuales, sin importar el período


def test_rf34_solo_administrador(app, client, esc):
    ingresar(client, identificacion="7001")
    assert client.get("/panel").status_code == 403


# RF-35 — Exportación CSV


def test_rf35_csv_de_citas_con_todas_las_filas_y_filtros(app, client, esc, aplicada, reloj):
    from app.models.cita import Cita

    reloj["ahora"] = hora("2026-10-08 12:00")
    with app.app_context():
        Cita.reservar(Usuario.buscar(otro_paciente(app, 1)), esc["campana"], esc["vacuna"], esc["franja_centro"])
    ingresar(client, identificacion="9001")
    respuesta = client.get(f"/reportes/citas.csv?desde={FRANJA_FECHA}&hasta={FRANJA_FECHA}")
    assert respuesta.mimetype == "text/csv"
    assert "attachment" in respuesta.headers["Content-Disposition"]
    filas = leer_csv(respuesta)
    assert filas[0][:3] == ["Id", "Campaña", "Paciente"]
    assert len(filas) == 3
    solo_centro = leer_csv(client.get(f"/reportes/citas.csv?punto_id={esc['centro']}"))
    assert len(solo_centro) == 2


def test_rf35_csv_de_aplicaciones_y_de_inventario(app, client, esc, aplicada):
    ingresar(client, identificacion="9001")
    aplicaciones = leer_csv(client.get("/reportes/aplicaciones.csv"))
    assert aplicaciones[1][3:7] == ["Influenza", "1", FRANJA_FECHA, "L-2041"]
    inventario = leer_csv(client.get("/reportes/inventario.csv?desde=2030-01-01"))
    assert {fila[2] for fila in inventario[1:]} == {"L-2041"}
    assert len(inventario) == 3  # Campus y Centro: no se filtra por fecha


def test_rf35_formulas_neutralizadas(app, client, esc, reloj):
    from app.models.cita import Cita

    malicioso = otro_paciente(app, 1, nombre="=HYPERLINK(\"x\")")
    with app.app_context():
        Cita.reservar(Usuario.buscar(malicioso), esc["campana"], esc["vacuna"], esc["franja"])
    ingresar(client, identificacion="9001")
    filas = leer_csv(client.get("/reportes/citas.csv"))
    assert filas[1][2] == "'=HYPERLINK(\"x\")"


def test_rf35_solo_administrador_exporta(app, client, esc):
    ingresar(client)
    for tipo in ("citas", "aplicaciones", "inventario"):
        assert client.get(f"/reportes/{tipo}.csv").status_code == 403


def test_tipo_de_reporte_desconocido(app, client, esc):
    ingresar(client, identificacion="9001")
    assert client.get("/reportes/usuarios.csv").status_code == 404


def test_menu_del_paciente_tiene_historial(app, client, esc):
    ingresar(client)
    assert ">Historial</a>" in client.get("/").get_data(as_text=True)


def test_panel_con_encabezado_en_la_banda_y_tarjetas_sueltas(app, client, esc):
    ingresar(client, identificacion="9001")
    html = client.get("/panel").get_data(as_text=True)
    banda = html[html.index('<header class="banda"'):html.index("</header>")]
    assert "Resumen de la jornada" in banda
    assert "Nueva campaña" in banda
    assert '<main id="contenido" class="tablero"' in html
    assert html.index("</header>") < html.index('class="indicadores"')


def test_filtros_campanas_y_franjas_en_una_sola_tarjeta(app, client, esc):
    ingresar(client, identificacion="9001")
    html = client.get("/panel").get_data(as_text=True)
    inicio = html.index('class="tarjeta-panel tarjeta-unida"')
    tarjeta = html[inicio:html.index('class="tarjeta-panel"', inicio)]
    for parte in ('name="campana_id"', "Campañas", "Próximas franjas"):
        assert parte in tarjeta
