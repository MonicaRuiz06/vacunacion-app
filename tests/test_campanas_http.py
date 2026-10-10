"""Pruebas de las rutas de catálogos, campañas y franjas (M04-F/V)."""

import pytest

from app.models.campana import Campana
from app.models.franja import Franja
from tests.conftest import (
    crear_campana,
    crear_cita,
    crear_franja,
    crear_paciente,
    crear_punto,
    crear_usuario,
    crear_vacuna,
    ingresar,
)

PAGINAS_ADMIN = ["/puntos", "/puntos/nuevo", "/vacunas", "/vacunas/nueva", "/lotes",
                 "/lotes/nuevo", "/campanas/nueva", "/franjas", "/franjas/nueva"]


@pytest.fixture
def admin(app, client, reloj):
    admin_id = crear_usuario(app, "administrador")
    ingresar(client, identificacion="9001")
    return admin_id


# Permisos


@pytest.mark.parametrize("ruta", PAGINAS_ADMIN)
def test_paciente_no_entra_a_paginas_administrativas(app, client, reloj, ruta):
    crear_paciente(app)
    ingresar(client)
    assert client.get(ruta).status_code == 403


@pytest.mark.parametrize("ruta", PAGINAS_ADMIN)
def test_vacunador_no_entra_a_paginas_administrativas(app, client, reloj, ruta):
    crear_usuario(app, "vacunador")
    ingresar(client, identificacion="9001")
    assert client.get(ruta).status_code == 403


def test_paciente_no_publica_por_post_directo(app, client, reloj):
    admin_id = crear_usuario(app, "administrador", identificacion="9002", correo="admin@example.com")
    campana_id = crear_campana(app, admin_id)
    crear_paciente(app)
    ingresar(client)
    assert client.post(f"/campanas/{campana_id}/publicar").status_code == 403


@pytest.mark.parametrize("ruta", PAGINAS_ADMIN)
def test_admin_ve_las_paginas_administrativas(client, admin, ruta):
    assert client.get(ruta).status_code == 200


def test_menu_del_administrador(client, admin):
    html = client.get("/").get_data(as_text=True)
    for texto in ("Campañas", "Franjas", "Puntos", "Vacunas", "Lotes", "Usuarios"):
        assert f">{texto}</a>" in html


# Puntos, vacunas y lotes


def test_admin_crea_punto(client, admin):
    respuesta = client.post("/puntos/nuevo", data={
        "nombre": "Punto Campus", "direccion": "Calle 5", "municipio": "Cali",
        "hora_apertura": "08:00", "hora_cierre": "16:00", "capacidad_diaria": "40"})
    assert respuesta.status_code == 303
    assert "Punto Campus" in client.get("/puntos").get_data(as_text=True)


def test_punto_invalido_muestra_error_por_campo(client, admin):
    respuesta = client.post("/puntos/nuevo", data={
        "nombre": "Punto Campus", "direccion": "Calle 5", "hora_apertura": "16:00",
        "hora_cierre": "08:00", "capacidad_diaria": "40"})
    assert respuesta.status_code == 400
    assert 'id="hora_cierre-error"' in respuesta.get_data(as_text=True)


def test_admin_edita_punto(app, client, admin):
    punto_id = crear_punto(app)
    assert client.get(f"/puntos/{punto_id}/editar").status_code == 200
    respuesta = client.post(f"/puntos/{punto_id}/editar", data={
        "nombre": "Punto Campus Norte", "direccion": "Calle 5", "hora_apertura": "07:00",
        "hora_cierre": "17:00", "capacidad_diaria": "60"})
    assert respuesta.status_code == 303
    assert "Punto Campus Norte" in client.get("/puntos").get_data(as_text=True)


def test_editar_punto_inexistente(client, admin):
    assert client.get("/puntos/999/editar").status_code == 404


def test_admin_crea_vacuna_y_lote(client, admin):
    client.post("/vacunas/nueva", data={"nombre": "Influenza", "fabricante": "Demo",
                                        "dosis_requeridas": "2"})
    assert "Influenza" in client.get("/vacunas").get_data(as_text=True)
    respuesta = client.post("/lotes/nuevo", data={"vacuna_id": "1", "codigo": "L-2041",
                                                  "fecha_vencimiento": "2026-11-30"})
    assert respuesta.status_code == 303
    html = client.get("/lotes").get_data(as_text=True)
    assert "L-2041" in html
    assert "Vigente" in html


def test_lote_vencido_se_marca(app, client, admin):
    crear_vacuna(app)
    client.post("/lotes/nuevo", data={"vacuna_id": "1", "codigo": "VIEJO",
                                      "fecha_vencimiento": "2026-10-01"})
    assert "Vencido" in client.get("/lotes").get_data(as_text=True)


# Campañas


def test_admin_crea_campana_con_puntos_y_vacunas(app, client, admin):
    punto = crear_punto(app)
    vacuna = crear_vacuna(app)
    respuesta = client.post("/campanas/nueva", data={
        "nombre": "Jornada de bienestar", "descripcion": "Campaña ficticia",
        "fecha_inicio": "2026-11-10", "fecha_fin": "2026-11-20",
        "puntos": [str(punto)], "vacunas": [str(vacuna)]})
    assert respuesta.status_code == 303
    html = client.get("/campanas/1").get_data(as_text=True)
    assert "Jornada de bienestar" in html
    assert "Borrador" in html
    assert "Punto Campus" in html
    assert "Influenza" in html


def test_publicar_incompleta_muestra_el_motivo(app, client, admin):
    campana_id = crear_campana(app, admin)
    respuesta = client.post(f"/campanas/{campana_id}/publicar", follow_redirects=True)
    assert "al menos un punto" in respuesta.get_data(as_text=True)
    with app.app_context():
        assert Campana.buscar(campana_id).estado == "borrador"


def test_publicar_pausar_y_reanudar(app, client, admin):
    punto = crear_punto(app)
    vacuna = crear_vacuna(app)
    crear_franja(app, punto)
    campana_id = crear_campana(app, admin, puntos=[punto], vacunas=[vacuna])
    for accion, estado in (("publicar", "publicada"), ("pausar", "pausada"),
                           ("reanudar", "publicada")):
        assert client.post(f"/campanas/{campana_id}/{accion}").status_code == 303
        with app.app_context():
            assert Campana.buscar(campana_id).estado == estado


def test_editar_campana_que_afecta_citas_muestra_error(app, client, admin):
    punto = crear_punto(app)
    vacuna = crear_vacuna(app)
    otra = crear_vacuna(app, nombre="Tétanos")
    franja = crear_franja(app, punto)
    campana_id = crear_campana(app, admin, puntos=[punto], vacunas=[vacuna])
    crear_cita(app, crear_paciente(app), campana_id, vacuna, franja)
    respuesta = client.post(f"/campanas/{campana_id}/editar", data={
        "nombre": "Jornada de bienestar", "descripcion": "Campaña ficticia",
        "fecha_inicio": "2026-11-10", "fecha_fin": "2026-11-20",
        "puntos": [str(punto)], "vacunas": [str(otra)]})
    assert respuesta.status_code == 400
    assert "cita" in respuesta.get_data(as_text=True)


def test_paciente_ve_solo_campanas_publicadas(app, client, reloj):
    admin_id = crear_usuario(app, "administrador")
    punto = crear_punto(app)
    vacuna = crear_vacuna(app)
    crear_franja(app, punto)
    publicada = crear_campana(app, admin_id, puntos=[punto], vacunas=[vacuna], nombre="Publicada")
    crear_campana(app, admin_id, nombre="En borrador")
    with app.app_context():
        Campana.buscar(publicada).publicar(admin_id)
    crear_paciente(app)
    ingresar(client)
    html = client.get("/campanas").get_data(as_text=True)
    assert "Publicada" in html
    assert "En borrador" not in html
    assert client.get("/campanas/2").status_code == 404  # borrador no visible


# Franjas


def test_admin_crea_franja(app, client, admin):
    punto = crear_punto(app)
    respuesta = client.post("/franjas/nueva", data={
        "punto_id": str(punto), "fecha": "2026-11-14", "hora_inicio": "09:00",
        "hora_fin": "09:30", "cupos": "5"})
    assert respuesta.status_code == 303
    assert "09:00" in client.get("/franjas").get_data(as_text=True)


def test_franja_superpuesta_muestra_error(app, client, admin):
    punto = crear_punto(app)
    crear_franja(app, punto)
    respuesta = client.post("/franjas/nueva", data={
        "punto_id": str(punto), "fecha": "2026-11-14", "hora_inicio": "09:15",
        "hora_fin": "09:45", "cupos": "5"})
    assert respuesta.status_code == 400
    assert "se cruza" in respuesta.get_data(as_text=True)


def test_reducir_cupos_por_debajo_de_la_ocupacion(app, client, admin):
    punto = crear_punto(app)
    vacuna = crear_vacuna(app)
    franja = crear_franja(app, punto, cupos=3)
    campana_id = crear_campana(app, admin, puntos=[punto], vacunas=[vacuna])
    for numero in range(2):
        usuario_id = crear_paciente(app, identificacion=f"10{numero}", correo=f"p{numero}@example.com")
        crear_cita(app, usuario_id, campana_id, vacuna, franja)
    respuesta = client.post(f"/franjas/{franja}/editar", data={"cupos": "1"})
    assert respuesta.status_code == 400
    assert client.post(f"/franjas/{franja}/editar", data={"cupos": "2"}).status_code == 303
    with app.app_context():
        assert Franja.buscar(franja).cupos == 2


def test_formulario_rechaza_campana_que_empieza_antes_de_hoy(client, admin):
    respuesta = client.post("/campanas/nueva", data={
        "nombre": "Jornada pasada", "descripcion": "Ficticia",
        "fecha_inicio": "2026-10-01", "fecha_fin": "2026-10-20"})
    assert respuesta.status_code == 400
    assert 'id="fecha_inicio-error"' in respuesta.get_data(as_text=True)
