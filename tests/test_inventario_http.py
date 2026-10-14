"""Pruebas de las rutas de inventario (M05-F/V)."""

import pytest

from app.db import get_db
from app.models.inventario import registrar_entrada
from app.models.usuario import Usuario
from tests.conftest import (
    crear_lote,
    crear_paciente,
    crear_punto,
    crear_usuario,
    crear_vacuna,
    ingresar,
)


@pytest.fixture
def datos(app, reloj):
    admin = crear_usuario(app, "administrador")
    campus = crear_punto(app, "Punto Campus")
    centro = crear_punto(app, "Punto Centro")
    vacuna = crear_vacuna(app)
    lote = crear_lote(app, vacuna)
    with app.app_context():
        inventario = registrar_entrada(campus, lote, 10, "Entrega inicial", admin)
        registrar_entrada(centro, lote, 4, "Entrega inicial", admin)
    return {"admin": admin, "campus": campus, "centro": centro, "lote": lote,
            "inventario": inventario}


def ingresar_admin(client):
    ingresar(client, identificacion="9001")


def test_paciente_no_ve_inventario(app, client, datos):
    crear_paciente(app)
    ingresar(client)
    assert client.get("/inventario").status_code == 403


def test_vacunador_ve_solo_sus_puntos_y_no_modifica(app, client, datos):
    vacunador = crear_usuario(app, "vacunador", identificacion="7001", correo="juan@example.com")
    with app.app_context():
        Usuario.buscar(vacunador).asignar_puntos([datos["campus"]], datos["admin"])
    ingresar(client, identificacion="7001")
    html = client.get("/inventario").get_data(as_text=True)
    assert "Punto Campus" in html
    assert "Punto Centro" not in html
    assert ">Inventario</a>" in client.get("/").get_data(as_text=True)
    assert client.get("/inventario/entrada").status_code == 403
    assert client.post(f"/inventario/{datos['inventario']}/ajuste",
                       data={"cantidad": "-1", "motivo": "x"}).status_code == 403
    assert client.get("/inventario/movimientos").status_code == 403


def test_admin_registra_entrada_por_formulario(app, client, datos):
    ingresar_admin(client)
    assert client.get("/inventario/entrada").status_code == 200
    respuesta = client.post("/inventario/entrada", data={
        "punto_id": str(datos["campus"]), "lote_id": str(datos["lote"]),
        "cantidad": "5", "motivo": "Segunda entrega", "clave": "abc"})
    assert respuesta.status_code == 303
    with app.app_context():
        saldo = get_db().execute("SELECT cantidad_disponible FROM inventarios_biologicos WHERE id = ?",
                                 (datos["inventario"],)).fetchone()[0]
    assert saldo == 15


def test_enviar_dos_veces_el_mismo_formulario_no_duplica(app, client, datos):
    ingresar_admin(client)
    formulario = {"punto_id": str(datos["campus"]), "lote_id": str(datos["lote"]),
                  "cantidad": "5", "motivo": "Entrega", "clave": "repetida"}
    client.post("/inventario/entrada", data=formulario)
    client.post("/inventario/entrada", data=formulario)
    with app.app_context():
        total = get_db().execute("SELECT COUNT(*) FROM movimientos_inventario WHERE clave = 'repetida'"
                                 ).fetchone()[0]
    assert total == 1


def test_entrada_invalida_muestra_errores(client, datos):
    ingresar_admin(client)
    respuesta = client.post("/inventario/entrada", data={
        "punto_id": "", "lote_id": str(datos["lote"]), "cantidad": "0", "motivo": ""})
    html = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 400
    assert 'id="cantidad-error"' in html
    assert 'id="motivo-error"' in html


def test_ajuste_que_deja_negativo_muestra_error(client, datos):
    ingresar_admin(client)
    ruta = f"/inventario/{datos['inventario']}/ajuste"
    assert client.get(ruta).status_code == 200
    respuesta = client.post(ruta, data={"cantidad": "-11", "motivo": "Pérdida"})
    assert respuesta.status_code == 400
    assert client.post(ruta, data={"cantidad": "-2", "motivo": "Dosis dañadas"}).status_code == 303


def test_movimientos_muestran_autor_y_motivo(client, datos):
    ingresar_admin(client)
    client.post(f"/inventario/{datos['inventario']}/ajuste",
                data={"cantidad": "-2", "motivo": "Dosis dañadas"})
    html = client.get("/inventario/movimientos").get_data(as_text=True)
    assert "Dosis dañadas" in html
    assert "Ana Díaz" in html
    assert "-2" in html


def test_inventario_muestra_saldo_y_estado_del_lote(client, datos):
    ingresar_admin(client)
    html = client.get("/inventario").get_data(as_text=True)
    assert "L-2041" in html
    assert "Vigente" in html
    assert ">10<" in html
