"""Pruebas de avisos y correo (M06): RF-05–06, RF-36–37."""

import pytest

from app.db import get_db
from app.models.notificacion import Notificacion, avisar
from app.models.usuario import Usuario
from app.utils import enviar_correo
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


@pytest.fixture
def datos(app, reloj):
    """Administrador, vacunador del Punto Campus, paciente y una cita en Campus."""
    admin = crear_usuario(app, "administrador")
    vacunador = crear_usuario(app, "vacunador", identificacion="7001", correo="juan@example.com")
    campus = crear_punto(app, "Punto Campus")
    centro = crear_punto(app, "Punto Centro")
    vacuna = crear_vacuna(app)
    franja_campus = crear_franja(app, campus)
    franja_centro = crear_franja(app, centro)
    campana = crear_campana(app, admin, puntos=[campus, centro], vacunas=[vacuna])
    paciente = crear_paciente(app)
    otro = crear_paciente(app, identificacion="1002", correo="otro@example.com")
    cita_campus = crear_cita(app, paciente, campana, vacuna, franja_campus)
    cita_centro = crear_cita(app, otro, campana, vacuna, franja_centro)
    with app.app_context():
        Usuario.buscar(vacunador).asignar_puntos([campus], admin)
    return {"admin": admin, "vacunador": vacunador, "paciente": paciente, "otro": otro,
            "campus": campus, "cita_campus": cita_campus, "cita_centro": cita_centro}


def crear_aviso(app, usuario_id, cita_id=None, enviar=True):
    """Guarda un aviso como lo hará una cancelación: primero el aviso, luego el correo."""
    with app.app_context():
        db = get_db()
        with db:
            aviso = avisar(usuario_id, "Cita cancelada", "Tu cita fue cancelada. Motivo: prueba.",
                           cita_id)
        if enviar:
            aviso.enviar()
        return aviso.id


def estado_correo(app, aviso_id):
    with app.app_context():
        aviso = Notificacion.buscar(aviso_id)
        return aviso.correo_estado, aviso.correo_intentos


# Envío por SMTP


def test_correo_sale_por_smtp(app, smtp_falso):
    with app.app_context():
        assert enviar_correo("laura@example.com", "Hola", "Texto de prueba") is True
    mensaje = smtp_falso["enviados"][0]
    assert mensaje["To"] == "laura@example.com"
    assert mensaje["From"] == "vacunacion@example.com"
    assert mensaje["Subject"] == "Hola"


def test_caida_del_servidor_devuelve_false(app, smtp_falso):
    smtp_falso["falla"] = True
    with app.app_context():
        assert enviar_correo("laura@example.com", "Hola", "Texto") is False


def test_sin_servidor_configurado_no_finge_envio(app):
    app.config.update(CORREOS_ENVIADOS=None, MAIL_SERVER=None)
    with app.app_context():
        assert enviar_correo("laura@example.com", "Hola", "Texto") is False


# RF-36 — Aviso interno y correo


def test_rf36_aviso_guardado_y_correo_enviado(app, datos, smtp_falso):
    aviso_id = crear_aviso(app, datos["paciente"], datos["cita_campus"])
    assert estado_correo(app, aviso_id) == ("enviado", 1)
    assert smtp_falso["enviados"][0]["To"] == "laura@example.com"
    assert "Motivo: prueba" in smtp_falso["enviados"][0].get_content()


def test_rf37_fallo_de_correo_conserva_el_aviso(app, datos, smtp_falso):
    smtp_falso["falla"] = True
    aviso_id = crear_aviso(app, datos["paciente"], datos["cita_campus"])
    assert estado_correo(app, aviso_id) == ("fallido", 1)
    with app.app_context():
        avisos = Notificacion.de_usuario(datos["paciente"])
    assert [aviso.asunto for aviso in avisos] == ["Cita cancelada"]


def test_aviso_queda_pendiente_hasta_enviarse(app, datos):
    aviso_id = crear_aviso(app, datos["paciente"], datos["cita_campus"], enviar=False)
    assert estado_correo(app, aviso_id) == ("pendiente", 0)


def test_aviso_se_revierte_con_la_operacion(app, datos):
    # Si la operación de negocio falla, el aviso tampoco queda guardado.
    with app.app_context():
        db = get_db()
        with pytest.raises(RuntimeError):
            with db:
                avisar(datos["paciente"], "Cita cancelada", "Mensaje", datos["cita_campus"])
                raise RuntimeError("falla la cancelación")
        assert Notificacion.de_usuario(datos["paciente"]) == []


# RF-37 — Reintento manual según rol


def reintentar(app, aviso_id, actor_id):
    with app.app_context():
        Notificacion.buscar(aviso_id).reintentar(Usuario.buscar(actor_id))


def test_rf37_admin_reintenta_un_correo_fallido(app, datos, smtp_falso):
    smtp_falso["falla"] = True
    aviso_id = crear_aviso(app, datos["paciente"], datos["cita_campus"])
    smtp_falso["falla"] = False
    reintentar(app, aviso_id, datos["admin"])
    assert estado_correo(app, aviso_id) == ("enviado", 2)
    assert len(smtp_falso["enviados"]) == 1


def test_rf37_no_se_reintenta_un_correo_ya_enviado(app, datos, smtp_falso):
    aviso_id = crear_aviso(app, datos["paciente"], datos["cita_campus"])
    with pytest.raises(ValueError):
        reintentar(app, aviso_id, datos["admin"])
    assert len(smtp_falso["enviados"]) == 1


def test_rf37_vacunador_reintenta_solo_avisos_de_sus_puntos(app, datos, smtp_falso):
    smtp_falso["falla"] = True
    del_campus = crear_aviso(app, datos["paciente"], datos["cita_campus"])
    del_centro = crear_aviso(app, datos["otro"], datos["cita_centro"])
    smtp_falso["falla"] = False
    reintentar(app, del_campus, datos["vacunador"])
    with pytest.raises(PermissionError):
        reintentar(app, del_centro, datos["vacunador"])
    assert estado_correo(app, del_centro) == ("fallido", 1)


def test_rf37_vacunador_sin_asignacion_ya_no_reintenta(app, datos, smtp_falso):
    smtp_falso["falla"] = True
    aviso_id = crear_aviso(app, datos["paciente"], datos["cita_campus"])
    with app.app_context():
        Usuario.buscar(datos["vacunador"]).asignar_puntos([], datos["admin"])
    with pytest.raises(PermissionError):
        reintentar(app, aviso_id, datos["vacunador"])


def test_rf37_paciente_no_reintenta(app, datos, smtp_falso):
    smtp_falso["falla"] = True
    aviso_id = crear_aviso(app, datos["paciente"], datos["cita_campus"])
    with pytest.raises(PermissionError):
        reintentar(app, aviso_id, datos["paciente"])


def test_fallidos_segun_rol(app, datos, smtp_falso):
    smtp_falso["falla"] = True
    crear_aviso(app, datos["paciente"], datos["cita_campus"])
    crear_aviso(app, datos["otro"], datos["cita_centro"])
    with app.app_context():
        assert len(Notificacion.fallidos(Usuario.buscar(datos["admin"]))) == 2
        assert len(Notificacion.fallidos(Usuario.buscar(datos["vacunador"]))) == 1


# Pantallas (M06-F)


def test_paciente_ve_solo_sus_avisos_y_quedan_leidos(app, client, datos, smtp_falso):
    crear_aviso(app, datos["paciente"], datos["cita_campus"])
    crear_aviso(app, datos["otro"], datos["cita_centro"])
    ingresar(client)
    html = client.get("/avisos").get_data(as_text=True)
    assert html.count("Cita cancelada") == 1
    assert ">Avisos</a>" in client.get("/").get_data(as_text=True)
    with app.app_context():
        assert Notificacion.de_usuario(datos["paciente"])[0].leido_en is not None


def test_paciente_no_entra_a_fallidos(client, datos):
    ingresar(client)
    assert client.get("/avisos/fallidos").status_code == 403


def test_admin_reintenta_desde_la_pantalla(app, client, datos, smtp_falso):
    smtp_falso["falla"] = True
    aviso_id = crear_aviso(app, datos["paciente"], datos["cita_campus"])
    smtp_falso["falla"] = False
    ingresar(client, identificacion="9001")
    html = client.get("/avisos/fallidos").get_data(as_text=True)
    assert "laura@example.com" in html
    assert client.post(f"/avisos/{aviso_id}/reintentar").status_code == 303
    assert estado_correo(app, aviso_id) == ("enviado", 2)


def test_vacunador_no_reintenta_aviso_ajeno_por_post_directo(app, client, datos, smtp_falso):
    smtp_falso["falla"] = True
    aviso_id = crear_aviso(app, datos["otro"], datos["cita_centro"])
    ingresar(client, identificacion="7001")
    assert client.post(f"/avisos/{aviso_id}/reintentar").status_code == 403


def test_invitacion_fallida_avisa_al_administrador(app, client, datos, smtp_falso):
    smtp_falso["falla"] = True
    ingresar(client, identificacion="9001")
    respuesta = client.post("/usuarios/vacunador", data={
        "nombre_completo": "Marta Ruiz", "tipo_documento": "CC", "identificacion": "7002",
        "correo": "marta@example.com", "puntos": [str(datos["campus"])]}, follow_redirects=True)
    assert "no se pudo enviar" in respuesta.get_data(as_text=True)
