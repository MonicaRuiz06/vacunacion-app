"""Pruebas de aplicación, corrección, anulación y rectificación (M09):
RF-16, RF-27–30, RF-39, RF-41, RF-42."""

import threading

import pytest

from app.db import get_db
from app.models.cita import Cita
from app.models.dosis import DosisAplicada
from app.models.franja import Franja
from app.models.inventario import registrar_entrada
from app.models.usuario import Usuario
from app.utils import ErroresFormulario
from tests.conftest import (
    FRANJA_FECHA,
    aplicar,
    atender,
    crear_lote,
    crear_paciente,
    crear_usuario,
    hora,
    ingresar,
)

# El escenario `esc` tiene 10 dosis del lote L-2041 en Campus y en Centro.


def saldo(app, punto_id, lote_id):
    with app.app_context():
        fila = get_db().execute(
            "SELECT cantidad_disponible FROM inventarios_biologicos WHERE punto_id = ? AND lote_id = ?",
            (punto_id, lote_id)).fetchone()
        return fila[0] if fila else 0


def dosis(app, dosis_id):
    with app.app_context():
        return DosisAplicada.buscar(dosis_id)


def estado_cita(app, cita_id):
    with app.app_context():
        return Cita.buscar(cita_id).estado


def otro_paciente(app, numero):
    return crear_paciente(app, identificacion=f"40{numero}", correo=f"p{numero}@example.com")


def usuario(app, usuario_id):
    with app.app_context():
        return Usuario.buscar(usuario_id)


def dos_dosis(app, esc):
    with app.app_context():
        get_db().execute("UPDATE vacunas SET dosis_requeridas = 2 WHERE id = ?", (esc["vacuna"],))
        get_db().commit()


def segundo_lote(app, esc, codigo="L-3000", vence="2027-01-31", punto=None):
    lote = crear_lote(app, esc["vacuna"], codigo=codigo, fecha_vencimiento=vence)
    with app.app_context():
        registrar_entrada(punto or esc["campus"], lote, 5, "Entrega", esc["admin"])
    return lote


# RF-27 / RF-28 — Aplicación


def test_rf27_vacunador_aplica_y_descuenta(app, esc, reloj):
    cita_id = atender(app, esc, reloj, esc["paciente"])
    dosis_id = aplicar(app, esc, cita_id)
    aplicada = dosis(app, dosis_id)
    assert aplicada.estado == "vigente"
    assert aplicada.fecha_aplicacion == FRANJA_FECHA
    assert aplicada.registrado_por == esc["vacunador"]
    assert estado_cita(app, cita_id) == "aplicada"
    assert saldo(app, esc["campus"], esc["lote"]) == 9
    with app.app_context():
        tipos = [f[0] for f in get_db().execute("SELECT tipo FROM movimientos_inventario")]
    assert tipos[-1] == "aplicacion"


def test_rf27_administrador_no_aplica(app, esc, reloj):
    cita_id = atender(app, esc, reloj, esc["paciente"])
    with pytest.raises(PermissionError):
        aplicar(app, esc, cita_id, usuario_id=esc["admin"])


def test_rf27_vacunador_de_otro_punto_no_aplica(app, esc, reloj):
    otro = crear_usuario(app, "vacunador", identificacion="7002", correo="otro@example.com")
    cita_id = atender(app, esc, reloj, esc["paciente"])
    with pytest.raises(PermissionError):
        aplicar(app, esc, cita_id, usuario_id=otro)


def test_rf27_requiere_llegada(app, esc):
    with app.app_context():
        cita_id = Cita.reservar(usuario(app, esc["paciente"]), esc["campana"], esc["vacuna"], esc["franja"])
    with pytest.raises(ValueError):
        aplicar(app, esc, cita_id)


def test_rf27_lote_de_otra_vacuna_vencido_o_sin_saldo(app, esc, reloj):
    from tests.conftest import crear_vacuna

    tetanos = crear_vacuna(app, nombre="Tétanos")
    de_otra = crear_lote(app, tetanos, codigo="TT-1", fecha_vencimiento="2026-12-31")
    vencido = crear_lote(app, esc["vacuna"], codigo="VIEJO", fecha_vencimiento="2026-10-19")
    sin_saldo = crear_lote(app, esc["vacuna"], codigo="VACIO", fecha_vencimiento="2026-12-31")
    with app.app_context():
        registrar_entrada(esc["campus"], vencido, 3, "Entrega", esc["admin"])
    cita_id = atender(app, esc, reloj, esc["paciente"])
    for lote in (de_otra, vencido, sin_saldo):
        with pytest.raises(ValueError):
            aplicar(app, esc, cita_id, lote_id=lote)
    assert estado_cita(app, cita_id) == "presente"
    assert saldo(app, esc["campus"], vencido) == 3


def test_rf28_confirmar_dos_veces_descuenta_una(app, esc, reloj):
    cita_id = atender(app, esc, reloj, esc["paciente"])
    aplicar(app, esc, cita_id)
    with pytest.raises(ValueError):
        aplicar(app, esc, cita_id)
    assert saldo(app, esc["campus"], esc["lote"]) == 9


def test_rf28_dos_confirmaciones_simultaneas(app, esc, reloj):
    cita_id = atender(app, esc, reloj, esc["paciente"])
    salida = threading.Barrier(2)
    resultados = []

    def intentar():
        with app.app_context():  # conexión propia en cada hilo
            salida.wait()
            try:
                DosisAplicada.registrar(cita_id, Usuario.buscar(esc["vacunador"]), esc["lote"], 1)
                resultados.append("ok")
            except ValueError:
                resultados.append("rechazada")

    hilos = [threading.Thread(target=intentar) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    assert sorted(resultados) == ["ok", "rechazada"]
    assert saldo(app, esc["campus"], esc["lote"]) == 9


# RF-29 / RF-16 — Número de dosis y esquema


@pytest.mark.parametrize("numero", ["0", "-1", "2", "uno"])
def test_rf29_numero_fuera_del_esquema(app, esc, reloj, numero):
    cita_id = atender(app, esc, reloj, esc["paciente"])  # la vacuna tiene 1 dosis
    with pytest.raises(ErroresFormulario):
        aplicar(app, esc, cita_id, numero=numero)


def test_rf29_no_repite_numero_vigente_y_rf16_siguiente_dosis(app, esc, reloj):
    dos_dosis(app, esc)
    aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]), numero=1)
    segunda = atender(app, esc, reloj, esc["paciente"], esc["otra_franja"])  # RF-16 permite la 2.ª
    with pytest.raises(ErroresFormulario):
        aplicar(app, esc, segunda, numero=1)
    aplicar(app, esc, segunda, numero=2)
    reloj["ahora"] = hora("2026-10-08 12:00")
    with app.app_context():
        with pytest.raises(ValueError, match="todas las dosis"):
            Cita.reservar(usuario(app, esc["paciente"]), esc["campana"], esc["vacuna"],
                          esc["franja_centro"])


# RF-30 — Correcciones


def test_rf30_autor_corrige_lote_con_movimientos(app, esc, reloj):
    nuevo = segundo_lote(app, esc)
    dosis_id = aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]))
    with app.app_context():
        DosisAplicada.buscar(dosis_id).corregir(usuario(app, esc["vacunador"]), "Lote mal digitado",
                                                lote_id=nuevo)
        auditoria = get_db().execute("SELECT detalle, motivo FROM auditoria WHERE accion = 'dosis_corregida'"
                                     ).fetchone()
    assert dosis(app, dosis_id).lote_id == nuevo
    assert saldo(app, esc["campus"], esc["lote"]) == 10  # se repuso
    assert saldo(app, esc["campus"], nuevo) == 4  # se descontó
    assert auditoria["motivo"] == "Lote mal digitado"
    assert str(esc["lote"]) in auditoria["detalle"]  # el original queda en la auditoría


def test_rf30_corregir_numero_no_mueve_inventario(app, esc, reloj):
    dos_dosis(app, esc)
    dosis_id = aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]), numero=1)
    with app.app_context():
        DosisAplicada.buscar(dosis_id).corregir(usuario(app, esc["admin"]), "Era la segunda", numero_dosis=2)
    assert dosis(app, dosis_id).numero_dosis == 2
    assert saldo(app, esc["campus"], esc["lote"]) == 9


def test_rf30_otro_vacunador_o_autor_sin_punto_no_corrigen(app, esc, reloj):
    nuevo = segundo_lote(app, esc)
    otro = crear_usuario(app, "vacunador", identificacion="7002", correo="otro@example.com")
    with app.app_context():
        Usuario.buscar(otro).asignar_puntos([esc["campus"]], esc["admin"])
    dosis_id = aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]))
    with app.app_context():
        with pytest.raises(PermissionError):
            DosisAplicada.buscar(dosis_id).corregir(Usuario.buscar(otro), "Motivo", lote_id=nuevo)
        Usuario.buscar(esc["vacunador"]).asignar_puntos([], esc["admin"])
        with pytest.raises(PermissionError):
            DosisAplicada.buscar(dosis_id).corregir(Usuario.buscar(esc["vacunador"]), "Motivo", lote_id=nuevo)
        DosisAplicada.buscar(dosis_id).corregir(Usuario.buscar(esc["admin"]), "Motivo", lote_id=nuevo)


def test_rf30_lote_vencido_hoy_valido_en_la_fecha_real(app, esc, reloj):
    corto = segundo_lote(app, esc, codigo="CORTO", vence="2026-10-25")
    dosis_id = aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]))  # aplicada el 20
    reloj["ahora"] = hora("2026-10-30 10:00")  # el lote ya venció, pero servía el 20
    with app.app_context():
        DosisAplicada.buscar(dosis_id).corregir(usuario(app, esc["admin"]), "Lote real", lote_id=corto)
    assert dosis(app, dosis_id).lote_id == corto


def test_rf30_corregir_exige_motivo_y_algun_cambio(app, esc, reloj):
    dosis_id = aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]))
    with app.app_context():
        with pytest.raises(ErroresFormulario):
            DosisAplicada.buscar(dosis_id).corregir(usuario(app, esc["admin"]), "", numero_dosis=1)
        with pytest.raises(ValueError):
            DosisAplicada.buscar(dosis_id).corregir(usuario(app, esc["admin"]), "Nada cambia",
                                                    lote_id=esc["lote"], numero_dosis=1)


# RF-39 / RF-41 / RF-16 — Anulación


def test_rf39_anular_no_usada_repone_una_vez(app, esc, reloj):
    cita_id = atender(app, esc, reloj, esc["paciente"])
    dosis_id = aplicar(app, esc, cita_id)
    with app.app_context():
        DosisAplicada.buscar(dosis_id).anular(usuario(app, esc["admin"]), "Registro duplicado", dosis_usada=False)
        with pytest.raises(ValueError):
            DosisAplicada.buscar(dosis_id).anular(usuario(app, esc["admin"]), "Otra vez", dosis_usada=False)
        assert Franja.buscar(esc["franja"]).ocupados() == 1  # RF-41: conserva la capacidad
    assert dosis(app, dosis_id).estado == "anulada"
    assert estado_cita(app, cita_id) == "registro_anulado"
    assert saldo(app, esc["campus"], esc["lote"]) == 10


def test_rf39_anular_usada_no_repone(app, esc, reloj):
    dosis_id = aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]))
    with app.app_context():
        DosisAplicada.buscar(dosis_id).anular(usuario(app, esc["admin"]), "Dosis perdida", dosis_usada=True)
    assert saldo(app, esc["campus"], esc["lote"]) == 9


def test_rf39_solo_administrador_anula_y_rf16_vuelve_a_permitir_reservar(app, esc, reloj):
    dosis_id = aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]))
    with app.app_context():
        with pytest.raises(PermissionError):
            DosisAplicada.buscar(dosis_id).anular(usuario(app, esc["vacunador"]), "Motivo", False)
        DosisAplicada.buscar(dosis_id).anular(usuario(app, esc["admin"]), "Error de registro", False)
    reloj["ahora"] = hora("2026-10-08 12:00")
    with app.app_context():  # la anulada no cuenta en el esquema
        Cita.reservar(usuario(app, esc["paciente"]), esc["campana"], esc["vacuna"], esc["franja_centro"])


# RF-42 — Rectificación excepcional


def rectificar(app, esc, dosis_id, destino, lote=None, numero=1, motivo="Paciente equivocado"):
    with app.app_context():
        return DosisAplicada.buscar(dosis_id).rectificar(usuario(app, esc["admin"]), destino,
                                                         lote or esc["lote"], numero, motivo)


def test_rf42_rectifica_hacia_cita_presente_sin_doble_descuento(app, esc, reloj):
    original_cita = atender(app, esc, reloj, esc["paciente"])
    destino = atender(app, esc, reloj, otro_paciente(app, 1))
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:20")
    original = aplicar(app, esc, original_cita)  # se registró al paciente equivocado
    nueva_id = rectificar(app, esc, original, destino)
    nueva = dosis(app, nueva_id)
    assert dosis(app, original).estado == "anulada"
    assert estado_cita(app, original_cita) == "registro_anulado"
    assert estado_cita(app, destino) == "aplicada"
    assert (nueva.cita_id, nueva.rectifica_id, nueva.fecha_aplicacion) == (destino, original, FRANJA_FECHA)
    assert saldo(app, esc["campus"], esc["lote"]) == 9  # una sola unidad usada


def test_rf42_con_otro_lote_reconcilia(app, esc, reloj):
    nuevo = segundo_lote(app, esc)
    original_cita = atender(app, esc, reloj, esc["paciente"])
    destino = atender(app, esc, reloj, otro_paciente(app, 1))
    original = aplicar(app, esc, original_cita)
    rectificar(app, esc, original, destino, lote=nuevo)
    assert saldo(app, esc["campus"], esc["lote"]) == 10
    assert saldo(app, esc["campus"], nuevo) == 4


def test_rf42_destino_invalido_no_cambia_nada(app, esc, reloj):
    original_cita = atender(app, esc, reloj, esc["paciente"])
    original = aplicar(app, esc, original_cita)
    reloj["ahora"] = hora("2026-10-08 12:00")
    with app.app_context():
        reservada = Cita.reservar(usuario(app, otro_paciente(app, 1)), esc["campana"], esc["vacuna"],
                                  esc["otra_franja"])
    with app.app_context():  # el vacunador también atiende Centro para registrar esa llegada
        Usuario.buscar(esc["vacunador"]).asignar_puntos([esc["campus"], esc["centro"]], esc["admin"])
    en_centro = atender(app, esc, reloj, otro_paciente(app, 2), esc["franja_centro"])
    for destino in (reservada, en_centro, original_cita):
        with pytest.raises(ValueError):
            rectificar(app, esc, original, destino)
    assert dosis(app, original).estado == "vigente"
    assert estado_cita(app, original_cita) == "aplicada"
    assert saldo(app, esc["campus"], esc["lote"]) == 9


def test_rf42_solo_administrador(app, esc, reloj):
    original = aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]))
    destino = atender(app, esc, reloj, otro_paciente(app, 1))
    with app.app_context():
        with pytest.raises(PermissionError):
            DosisAplicada.buscar(original).rectificar(usuario(app, esc["vacunador"]), destino,
                                                      esc["lote"], 1, "Motivo")


# Pantallas (M09-F)


def test_vacunador_aplica_desde_la_agenda(app, client, esc, reloj):
    cita_id = atender(app, esc, reloj, esc["paciente"])
    ingresar(client, identificacion="7001")
    agenda = client.get(f"/citas?fecha={FRANJA_FECHA}").get_data(as_text=True)
    assert f"/citas/{cita_id}/aplicar" in agenda
    formulario = client.get(f"/citas/{cita_id}/aplicar").get_data(as_text=True)
    assert "L-2041" in formulario
    respuesta = client.post(f"/citas/{cita_id}/aplicar", data={"lote_id": str(esc["lote"]), "numero_dosis": "1"})
    assert respuesta.status_code == 303
    assert estado_cita(app, cita_id) == "aplicada"
    assert client.post(f"/citas/{cita_id}/aplicar",
                       data={"lote_id": str(esc["lote"]), "numero_dosis": "1"}).status_code == 409


def test_administrador_no_ve_el_formulario_de_aplicar(app, client, esc, reloj):
    cita_id = atender(app, esc, reloj, esc["paciente"])
    ingresar(client, identificacion="9001")
    assert client.get(f"/citas/{cita_id}/aplicar").status_code == 403


def test_pantallas_de_corregir_anular_y_rectificar(app, client, esc, reloj):
    nuevo = segundo_lote(app, esc)
    original_cita = atender(app, esc, reloj, esc["paciente"])
    destino = atender(app, esc, reloj, otro_paciente(app, 1))
    dosis_id = aplicar(app, esc, original_cita)
    ingresar(client, identificacion="9001")
    listado = client.get("/aplicaciones").get_data(as_text=True)
    assert "Laura Gómez" in listado
    assert client.post(f"/aplicaciones/{dosis_id}/corregir",
                       data={"lote_id": str(nuevo), "numero_dosis": "1", "motivo": ""}).status_code == 400
    assert client.post(f"/aplicaciones/{dosis_id}/corregir",
                       data={"lote_id": str(nuevo), "numero_dosis": "1", "motivo": "Lote real"}).status_code == 303
    pagina = client.get(f"/aplicaciones/{dosis_id}/rectificar").get_data(as_text=True)
    assert "Paciente" in pagina
    assert client.post(f"/aplicaciones/{dosis_id}/rectificar", data={
        "cita_id": str(destino), "lote_id": str(nuevo), "numero_dosis": "1",
        "motivo": "Paciente equivocado"}).status_code == 303
    assert estado_cita(app, destino) == "aplicada"


def test_anular_desde_la_pantalla(app, client, esc, reloj):
    dosis_id = aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]))
    ingresar(client, identificacion="9001")
    assert client.get(f"/aplicaciones/{dosis_id}/anular").status_code == 200
    assert client.post(f"/aplicaciones/{dosis_id}/anular",
                       data={"motivo": "Duplicado", "dosis_usada": "no"}).status_code == 303
    assert saldo(app, esc["campus"], esc["lote"]) == 10


def test_paciente_no_entra_a_aplicaciones(app, client, esc):
    ingresar(client)
    assert client.get("/aplicaciones").status_code == 403
