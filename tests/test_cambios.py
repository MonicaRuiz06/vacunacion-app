"""Pruebas de cambios que afectan citas y de desactivación (M08): RF-08, RF-13, RF-36, RF-40, RF-44."""

import pytest

from app.db import get_db
from app.models.campana import Campana
from app.models.cita import Cita, CitasAfectadas
from app.models.franja import Franja
from app.models.usuario import Usuario
from app.utils import ErroresFormulario
from tests.conftest import (
    aplicar,
    atender,
    FRANJA_FECHA,
    CONTRASENA,
    crear_paciente,
    crear_vacuna,
    hora,
    ingresar,
)


def reservar(app, esc, usuario_id, franja=None, vacuna=None):
    with app.app_context():
        return Cita.reservar(Usuario.buscar(usuario_id), esc["campana"],
                             vacuna or esc["vacuna"], franja or esc["franja"])


def estado(app, cita_id):
    with app.app_context():
        return Cita.buscar(cita_id).estado


def otro_paciente(app, numero):
    return crear_paciente(app, identificacion=f"30{numero}", correo=f"p{numero}@example.com")


def marcar(app, cita_id, nuevo_estado):
    with app.app_context():
        get_db().execute("UPDATE citas SET estado = ? WHERE id = ?", (nuevo_estado, cita_id))
        get_db().commit()


def avisos(app):
    with app.app_context():
        return get_db().execute("SELECT usuario_id, mensaje, correo_estado FROM notificaciones").fetchall()


# RF-13 — Cambios de campaña que afectan citas


def quitar_punto_centro(app, esc, motivo=None, confirmadas=None):
    """Retira el Punto Centro de la campaña."""
    with app.app_context():
        campana = Campana.buscar(esc["campana"])
        campana.puntos_ids = [esc["campus"]]
        campana.guardar(esc["admin"], motivo, confirmadas)


def test_rf13_cambio_sin_confirmar_muestra_las_citas_afectadas(app, esc):
    afectada = reservar(app, esc, esc["paciente"], franja=esc["franja_centro"])
    reservar(app, esc, otro_paciente(app, 1))  # en Campus: no se afecta
    with pytest.raises(CitasAfectadas) as error:
        quitar_punto_centro(app, esc)
    assert error.value.ids == [afectada]
    assert estado(app, afectada) == "reservada"
    with app.app_context():
        assert esc["centro"] in Campana.buscar(esc["campana"]).puntos_ids


def test_rf13_confirmar_exige_motivo(app, esc):
    afectada = reservar(app, esc, esc["paciente"], franja=esc["franja_centro"])
    with pytest.raises(ErroresFormulario) as error:
        quitar_punto_centro(app, esc, "", [afectada])
    assert "motivo" in error.value.errores
    assert estado(app, afectada) == "reservada"


def test_rf13_confirmado_cancela_avisa_y_conserva_las_demas(app, esc, reloj):
    afectada = reservar(app, esc, esc["paciente"], franja=esc["franja_centro"])
    presente = reservar(app, esc, otro_paciente(app, 1), franja=esc["franja_centro"])
    aplicada = reservar(app, esc, otro_paciente(app, 2), franja=esc["otra_franja"])
    no_afectada = reservar(app, esc, otro_paciente(app, 3))
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:10")
    with app.app_context():
        Cita.buscar(presente).registrar_llegada(Usuario.buscar(esc["admin"]))
    marcar(app, aplicada, "aplicada")
    quitar_punto_centro(app, esc, "El punto cierra por obras", [afectada, presente])
    assert estado(app, afectada) == "cancelada"
    assert estado(app, presente) == "cancelada"
    assert estado(app, aplicada) == "aplicada"
    assert estado(app, no_afectada) == "reservada"
    mensajes = avisos(app)
    assert len(mensajes) == 2
    assert all("El punto cierra por obras" in fila["mensaje"] for fila in mensajes)
    assert all(fila["correo_estado"] == "enviado" for fila in mensajes)
    with app.app_context():
        assert Campana.buscar(esc["campana"]).puntos_ids == [esc["campus"]]
        assert Franja.buscar(esc["franja_centro"]).ocupados() == 0


def test_rf13_si_la_lista_cambio_se_vuelve_a_confirmar(app, esc):
    primera = reservar(app, esc, esc["paciente"], franja=esc["franja_centro"])
    nueva = reservar(app, esc, otro_paciente(app, 1), franja=esc["franja_centro"])  # llegó después
    with pytest.raises(CitasAfectadas) as error:
        quitar_punto_centro(app, esc, "Cierre", [primera])
    assert error.value.ids == [primera, nueva]
    assert estado(app, primera) == "reservada"


def test_rf13_cambiar_fechas_y_quitar_vacuna(app, esc):
    tetanos = crear_vacuna(app, nombre="Tétanos")
    cita_id = reservar(app, esc, esc["paciente"])
    with app.app_context():
        campana = Campana.buscar(esc["campana"])
        campana.vacunas_ids = [esc["vacuna"], tetanos]
        campana.guardar(esc["admin"])  # agregar una vacuna no afecta citas
        campana.fecha_inicio = "2026-10-21"  # la franja es del 20
        with pytest.raises(CitasAfectadas):
            campana.guardar(esc["admin"])
        campana.guardar(esc["admin"], "Se aplaza el inicio", [cita_id])
    assert estado(app, cita_id) == "cancelada"


# RF-08 / RF-40 / RF-44 — Desactivación y reactivación de pacientes


def admin(app, esc):
    with app.app_context():
        return Usuario.buscar(esc["admin"])


def test_rf08_desactivar_muestra_las_citas_que_se_cancelan(app, esc):
    activa = reservar(app, esc, esc["paciente"])
    with app.app_context():
        paciente = Usuario.buscar(esc["paciente"])
        assert [cita.id for cita in paciente.citas_activas()] == [activa]
        with pytest.raises(CitasAfectadas):
            paciente.desactivar(Usuario.buscar(esc["admin"]), "Solicitud del paciente", [])
        assert Usuario.buscar(esc["paciente"]).activo == 1


def test_rf08_desactivar_cancela_avisa_y_cierra_sesiones(app, esc, reloj):
    with app.app_context():
        get_db().execute("UPDATE vacunas SET dosis_requeridas = 2 WHERE id = ?", (esc["vacuna"],))
        get_db().commit()
    aplicar(app, esc, atender(app, esc, reloj, esc["paciente"]))  # dosis 1 aplicada
    reloj["ahora"] = hora("2026-10-08 12:00")
    reservada = reservar(app, esc, esc["paciente"], franja=esc["franja_centro"])  # dosis 2
    with app.app_context():
        Usuario.buscar(esc["paciente"]).desactivar(Usuario.buscar(esc["admin"]),
                                                   "Datos duplicados", [reservada])
        paciente = Usuario.buscar(esc["paciente"])
        historial = get_db().execute("SELECT COUNT(*) FROM dosis_aplicadas").fetchone()[0]
        assert Usuario.autenticar("CC", "1001", CONTRASENA) is None
    assert paciente.activo == 0
    assert paciente.version_credenciales == 1
    assert estado(app, reservada) == "cancelada"
    assert historial == 1  # la historia se conserva
    assert "Datos duplicados" in avisos(app)[0]["mensaje"]


def test_rf08_desactivar_exige_motivo_y_administrador(app, esc):
    with app.app_context():
        paciente = Usuario.buscar(esc["paciente"])
        with pytest.raises(ErroresFormulario):
            paciente.desactivar(Usuario.buscar(esc["admin"]), "", [])
        with pytest.raises(PermissionError):
            paciente.desactivar(Usuario.buscar(esc["vacunador"]), "Motivo", [])
        with pytest.raises(PermissionError):
            Usuario.buscar(esc["vacunador"]).desactivar(Usuario.buscar(esc["admin"]), "Motivo", [])


def test_rf40_reactivar_permite_ingresar_sin_restaurar_citas(app, esc):
    cita_id = reservar(app, esc, esc["paciente"])
    with app.app_context():
        Usuario.buscar(esc["paciente"]).desactivar(Usuario.buscar(esc["admin"]), "Prueba", [cita_id])
        Usuario.buscar(esc["paciente"]).reactivar(Usuario.buscar(esc["admin"]))
        assert Usuario.autenticar("CC", "1001", CONTRASENA) is not None
        assert Franja.buscar(esc["franja"]).ocupados() == 0
    assert estado(app, cita_id) == "cancelada"


# Pantallas (M08-F)


def test_editar_campana_muestra_confirmacion_y_luego_cancela(app, client, esc):
    afectada = reservar(app, esc, esc["paciente"], franja=esc["franja_centro"])
    ingresar(client, identificacion="9001")
    datos = {"nombre": "Jornada de bienestar", "descripcion": "Campaña ficticia",
             "fecha_inicio": "2026-10-10", "fecha_fin": "2026-11-30",
             "puntos": [str(esc["campus"])], "vacunas": [str(esc["vacuna"])]}
    pagina = client.post(f"/campanas/{esc['campana']}/editar", data=datos)
    html = pagina.get_data(as_text=True)
    assert pagina.status_code == 409
    assert "Laura Gómez" in html
    assert 'name="citas_confirmadas"' in html
    sin_motivo = client.post(f"/campanas/{esc['campana']}/editar",
                             data={**datos, "citas_confirmadas": [str(afectada)], "motivo": ""})
    assert sin_motivo.status_code == 400
    confirmado = client.post(f"/campanas/{esc['campana']}/editar",
                             data={**datos, "citas_confirmadas": [str(afectada)], "motivo": "Cierre"})
    assert confirmado.status_code == 303
    assert estado(app, afectada) == "cancelada"


def test_admin_desactiva_y_reactiva_desde_usuarios(app, client, esc):
    cita_id = reservar(app, esc, esc["paciente"])
    paciente = app.test_client()
    ingresar(paciente)
    ingresar(client, identificacion="9001")
    assert "Desactivar" in client.get("/usuarios").get_data(as_text=True)
    ruta = f"/usuarios/{esc['paciente']}/desactivar"
    confirmar = client.get(ruta).get_data(as_text=True)
    assert "Influenza" in confirmar
    respuesta = client.post(ruta, data={"motivo": "Solicitud del paciente",
                                        "citas_confirmadas": [str(cita_id)]})
    assert respuesta.status_code == 303
    assert paciente.get("/perfil").status_code == 302  # su sesión se cerró
    assert "Reactivar" in client.get("/usuarios").get_data(as_text=True)
    assert client.post(f"/usuarios/{esc['paciente']}/reactivar").status_code == 303
    assert ingresar(paciente).status_code == 303


def test_paciente_no_desactiva_cuentas(app, client, esc):
    ingresar(client)
    assert client.post(f"/usuarios/{esc['paciente']}/desactivar", data={"motivo": "x"}).status_code == 403
