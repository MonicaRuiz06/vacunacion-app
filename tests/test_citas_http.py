"""Pruebas de las rutas de citas (M07-F/V)."""

from app.db import get_db
from app.models.cita import Cita
from app.models.usuario import Usuario
from tests.conftest import FRANJA_FECHA, crear_paciente, hora, ingresar


def reservar_por_formulario(client, esc):
    return client.post(f"/citas/nueva?campana_id={esc['campana']}", data={
        "vacuna_id": str(esc["vacuna"]), "franja_id": str(esc["franja"])})


def test_paciente_ve_boton_reservar_en_la_campana(client, esc):
    ingresar(client)
    html = client.get(f"/campanas/{esc['campana']}").get_data(as_text=True)
    assert f"/citas/nueva?campana_id={esc['campana']}" in html


def test_paciente_reserva_y_ve_su_cita(app, client, esc):
    ingresar(client)
    pagina = client.get(f"/citas/nueva?campana_id={esc['campana']}").get_data(as_text=True)
    assert "Punto Campus" in pagina
    respuesta = reservar_por_formulario(client, esc)
    assert respuesta.status_code == 303
    html = client.get("/citas").get_data(as_text=True)
    assert "Influenza" in html
    assert "Reservada" in html
    assert ">Citas</a>" in client.get("/").get_data(as_text=True)


def test_reserva_rechazada_muestra_el_motivo(client, esc):
    ingresar(client)
    reservar_por_formulario(client, esc)
    respuesta = reservar_por_formulario(client, esc)
    assert respuesta.status_code == 409
    assert "activa" in respuesta.get_data(as_text=True)


def test_personal_no_reserva_como_paciente(client, esc):
    ingresar(client, identificacion="9001")
    assert reservar_por_formulario(client, esc).status_code == 403


def test_paciente_cancela_su_cita(app, client, esc):
    ingresar(client)
    reservar_por_formulario(client, esc)
    assert client.get("/citas/1/cancelar").status_code == 200
    assert client.post("/citas/1/cancelar").status_code == 303
    with app.app_context():
        assert Cita.buscar(1).estado == "cancelada"


def test_paciente_no_toca_cita_ajena(app, client, esc):
    ingresar(client)
    reservar_por_formulario(client, esc)
    otro = app.test_client()
    crear_paciente(app, identificacion="2001", correo="otro@example.com")
    ingresar(otro, identificacion="2001")
    assert otro.post("/citas/1/cancelar").status_code == 403
    assert otro.get("/citas/1/reprogramar").status_code == 403


def test_paciente_reprograma_por_formulario(app, client, esc):
    ingresar(client)
    reservar_por_formulario(client, esc)
    assert client.get("/citas/1/reprogramar").status_code == 200
    respuesta = client.post("/citas/1/reprogramar", data={
        "campana_id": str(esc["campana"]), "vacuna_id": str(esc["vacuna"]),
        "franja_id": str(esc["otra_franja"])})
    assert respuesta.status_code == 303
    with app.app_context():
        assert Cita.buscar(1).franja_id == esc["otra_franja"]


def test_agenda_del_vacunador_y_llegada(app, client, esc, reloj):
    paciente = app.test_client()
    ingresar(paciente)
    reservar_por_formulario(paciente, esc)
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:10")
    ingresar(client, identificacion="7001")
    html = client.get(f"/citas?fecha={FRANJA_FECHA}").get_data(as_text=True)
    assert "Laura Gómez" in html
    assert "Registrar llegada" in html
    assert client.post("/citas/1/llegada").status_code == 303
    with app.app_context():
        assert Cita.buscar(1).estado == "presente"
    assert client.get("/citas/1/no-aplicada").status_code == 200
    assert client.post("/citas/1/no-aplicada", data={"motivo": ""}).status_code == 400
    assert client.post("/citas/1/no-aplicada", data={"motivo": "Fiebre"}).status_code == 303
    with app.app_context():
        assert Cita.buscar(1).estado == "no_aplicada"


def test_paciente_no_registra_llegada(client, esc):
    ingresar(client)
    reservar_por_formulario(client, esc)
    assert client.post("/citas/1/llegada").status_code == 403


def test_personal_cancela_con_motivo_obligatorio(app, client, esc):
    paciente = app.test_client()
    ingresar(paciente)
    reservar_por_formulario(paciente, esc)
    ingresar(client, identificacion="9001")
    sin_motivo = client.post("/citas/1/cancelar", data={"motivo": ""})
    assert sin_motivo.status_code == 400
    assert 'id="motivo-error"' in sin_motivo.get_data(as_text=True)
    assert client.post("/citas/1/cancelar", data={"motivo": "Punto cerrado"}).status_code == 303
    assert "Punto cerrado" in paciente.get("/avisos").get_data(as_text=True)


def test_vacunador_no_ve_citas_de_otros_puntos(app, client, esc):
    paciente = app.test_client()
    ingresar(paciente)
    paciente.post(f"/citas/nueva?campana_id={esc['campana']}", data={
        "vacuna_id": str(esc["vacuna"]), "franja_id": str(esc["franja_centro"])})
    ingresar(client, identificacion="7001")
    assert "Laura Gómez" not in client.get("/citas").get_data(as_text=True)
    assert client.post("/citas/1/llegada").status_code == 403


def test_listado_procesa_vencidas_al_consultar(app, client, esc, reloj):
    ingresar(client)
    reservar_por_formulario(client, esc)
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 10:00")
    assert "No asistió" in client.get("/citas").get_data(as_text=True)
    with app.app_context():
        assert get_db().execute("SELECT estado FROM citas").fetchone()[0] == "no_asistio"
        assert Usuario.buscar(1).rol == "administrador"
