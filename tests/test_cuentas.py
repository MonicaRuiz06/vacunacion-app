"""Pruebas del modelo de cuentas (M02): RF-01–07, RF-43–44."""

from datetime import timedelta

import pytest

from app.db import get_db
from app.models.paciente import Paciente
from app.models.usuario import Usuario, crear_token, usar_token, validar_contrasena
from app.utils import ErroresFormulario
from tests.conftest import CONTRASENA, crear_paciente, crear_punto, crear_usuario, datos_paciente


def errores_al_guardar(app, contrasena=CONTRASENA, **cambios):
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Paciente(**datos_paciente(**cambios)).guardar(contrasena)
        return error.value.errores


# RF-01 — Autorregistro


def test_rf01_registro_completo_crea_usuario_y_paciente(app, reloj):
    usuario_id = crear_paciente(app, telefono="3001234567", municipio="Cali")
    with app.app_context():
        usuario = Usuario.buscar(usuario_id)
        paciente = Paciente.buscar_por_usuario(usuario_id)
    assert usuario.rol == "paciente"
    assert paciente.nombre_completo == "Laura Gómez"
    assert paciente.municipio == "Cali"


@pytest.mark.parametrize("campo", ["nombre_completo", "identificacion", "correo", "fecha_nacimiento"])
def test_rf01_rechaza_campo_obligatorio_vacio(app, reloj, campo):
    assert campo in errores_al_guardar(app, **{campo: ""})


def test_rf01_opcionales_pueden_faltar(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        paciente = Paciente.buscar_por_usuario(usuario_id)
    assert paciente.telefono is None
    assert paciente.genero is None


# RF-02 / RF-43 — Identidad única y normalizada


def test_rf43_normaliza_documento_y_correo(app, reloj):
    usuario_id = crear_paciente(app, identificacion="  00123ab ", correo=" Laura@Example.COM ")
    with app.app_context():
        usuario = Usuario.buscar(usuario_id)
    assert usuario.identificacion == "00123AB"
    assert usuario.correo == "laura@example.com"


def test_rf02_rechaza_documento_duplicado_normalizado(app, reloj):
    crear_paciente(app, identificacion="00123")
    errores = errores_al_guardar(app, identificacion=" 00123 ", correo="otra@example.com")
    assert "identificacion" in errores


def test_rf02_rechaza_correo_duplicado_sin_importar_mayusculas(app, reloj):
    crear_paciente(app)
    errores = errores_al_guardar(app, identificacion="2002", correo="LAURA@example.com")
    assert "correo" in errores


def test_rf02_mismo_numero_con_otro_tipo_es_valido(app, reloj):
    crear_paciente(app, identificacion="123")
    crear_paciente(app, tipo_documento="CE", identificacion="123", correo="otra@example.com")


def test_rf02_tipo_de_documento_invalido(app, reloj):
    assert "tipo_documento" in errores_al_guardar(app, tipo_documento="TI")


def test_rf02_correo_invalido(app, reloj):
    assert "correo" in errores_al_guardar(app, correo="laura@")


# RF-03 — Edad mínima (hoy es 2026-10-08)


def test_rf03_rechaza_un_dia_antes_de_cumplir_16(app, reloj):
    errores = errores_al_guardar(app, fecha_nacimiento="2010-10-09", declaracion_responsable="2026-10-08")
    assert "fecha_nacimiento" in errores


def test_rf03_acepta_el_dia_que_cumple_16_con_declaracion(app, reloj):
    crear_paciente(app, fecha_nacimiento="2010-10-08", declaracion_responsable="2026-10-08")


def test_rf03_exige_declaracion_entre_16_y_17(app, reloj):
    errores = errores_al_guardar(app, fecha_nacimiento="2009-01-01")
    assert "declaracion_responsable" in errores


def test_rf03_desde_18_no_exige_declaracion(app, reloj):
    crear_paciente(app, fecha_nacimiento="2008-10-08")


# RF-04 / RF-05 — Contraseña


@pytest.mark.parametrize("contrasena", ["Ab#1", "clave#123", "CLAVE#123", "Clave#abc", "Clave1234"])
def test_rf05_politica_de_contrasena(contrasena):
    assert validar_contrasena(contrasena)


def test_rf05_contrasena_valida_no_da_error():
    assert validar_contrasena("Clave#123") is None


def test_rf05_contrasena_se_guarda_con_hash(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        usuario = Usuario.buscar(usuario_id)
    assert CONTRASENA not in usuario.password_hash


def test_rf04_cuenta_activa_sin_verificar_correo(app, reloj):
    crear_paciente(app)
    with app.app_context():
        assert Usuario.autenticar("CC", "1001", CONTRASENA) is not None


def test_autenticar_normaliza_y_rechaza_contrasena_incorrecta(app, reloj):
    crear_paciente(app, identificacion="00123")
    with app.app_context():
        assert Usuario.autenticar("cc", " 00123 ", CONTRASENA) is not None
        assert Usuario.autenticar("CC", "123", CONTRASENA) is None
        assert Usuario.autenticar("CC", "00123", "Otra#123") is None


# RF-05 — Enlaces de 30 minutos y un solo uso


def test_rf05_token_cambia_contrasena_una_sola_vez(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        with get_db():
            token = crear_token(usuario_id, "recuperacion")
        usar_token(token, "recuperacion", "Nueva#123")
        assert Usuario.autenticar("CC", "1001", "Nueva#123") is not None
        with pytest.raises(ValueError):
            usar_token(token, "recuperacion", "Otra#1234")


def test_rf05_token_vence_a_los_30_minutos(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        with get_db():
            token = crear_token(usuario_id, "recuperacion")
        reloj["ahora"] += timedelta(minutes=30)
        with pytest.raises(ValueError):
            usar_token(token, "recuperacion", "Nueva#123")


def test_rf05_token_sirve_antes_de_vencer(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        with get_db():
            token = crear_token(usuario_id, "recuperacion")
        reloj["ahora"] += timedelta(minutes=29, seconds=59)
        usar_token(token, "recuperacion", "Nueva#123")


def test_rf05_nuevo_token_invalida_el_anterior(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        with get_db():
            viejo = crear_token(usuario_id, "recuperacion")
            crear_token(usuario_id, "recuperacion")
        with pytest.raises(ValueError):
            usar_token(viejo, "recuperacion", "Nueva#123")


def test_rf05_token_de_otro_proposito_no_sirve(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        with get_db():
            token = crear_token(usuario_id, "recuperacion")
        with pytest.raises(ValueError):
            usar_token(token, "invitacion", "Nueva#123")


def test_rf05_solo_se_guarda_el_hash_del_token(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        with get_db():
            token = crear_token(usuario_id, "recuperacion")
        guardado = get_db().execute("SELECT token_hash FROM tokens_cuenta").fetchone()[0]
    assert guardado != token


# RF-06 — Vacunadores y puntos


def test_rf06_vacunador_invitado_no_puede_ingresar_sin_contrasena(app, reloj):
    with app.app_context():
        vacunador = Usuario(nombre_completo="Juan", tipo_documento="CC", identificacion="7001",
                            correo="juan@example.com", rol="vacunador")
        vacunador.guardar()
        assert Usuario.autenticar("CC", "7001", "") is None


def test_rf06_asignar_puntos_reemplaza_los_anteriores(app, reloj):
    campus = crear_punto(app, "Campus")
    centro = crear_punto(app, "Centro")
    admin_id = crear_usuario(app, "administrador")
    vacunador_id = crear_usuario(app, "vacunador", identificacion="7001", correo="juan@example.com")
    with app.app_context():
        vacunador = Usuario.buscar(vacunador_id)
        vacunador.asignar_puntos([campus, centro], admin_id)
        vacunador.asignar_puntos([centro], admin_id)
        assert [punto["id"] for punto in vacunador.puntos()] == [centro]
        assert vacunador.tiene_punto(centro)
        assert not vacunador.tiene_punto(campus)


def test_rf06_rechaza_puntos_inexistentes(app, reloj):
    admin_id = crear_usuario(app, "administrador")
    vacunador_id = crear_usuario(app, "vacunador", identificacion="7001", correo="juan@example.com")
    with app.app_context():
        with pytest.raises(ValueError):
            Usuario.buscar(vacunador_id).asignar_puntos([999], admin_id)


# RF-07 — Perfil editable con trazabilidad


def test_rf07_actualizar_perfil_conserva_ids_y_registra_auditoria(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        paciente = Paciente.buscar_por_usuario(usuario_id)
        paciente_id = paciente.id
        paciente.nombre_completo = "Laura Gómez Ruiz"
        paciente.telefono = "3001112233"
        paciente.actualizar()
        actualizado = Paciente.buscar_por_usuario(usuario_id)
        auditoria = get_db().execute("SELECT accion, detalle FROM auditoria").fetchall()
    assert actualizado.id == paciente_id
    assert actualizado.nombre_completo == "Laura Gómez Ruiz"
    assert auditoria[0]["accion"] == "perfil_actualizado"
    assert "Laura Gómez Ruiz" in auditoria[0]["detalle"]


def test_rf07_no_acepta_correo_de_otra_cuenta(app, reloj):
    crear_paciente(app, identificacion="2002", correo="otra@example.com")
    usuario_id = crear_paciente(app)
    with app.app_context():
        paciente = Paciente.buscar_por_usuario(usuario_id)
        paciente.correo = "OTRA@example.com"
        with pytest.raises(ErroresFormulario) as error:
            paciente.actualizar()
    assert "correo" in error.value.errores


def test_rf07_no_acepta_nacimiento_menor_de_16(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        paciente = Paciente.buscar_por_usuario(usuario_id)
        paciente.fecha_nacimiento = "2015-01-01"
        with pytest.raises(ErroresFormulario):
            paciente.actualizar()


# RF-44 — Cambios de acceso cierran sesiones e invalidan enlaces


def test_rf44_cambiar_correo_sube_version_y_borra_enlaces(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        with get_db():
            token = crear_token(usuario_id, "recuperacion")
        paciente = Paciente.buscar_por_usuario(usuario_id)
        paciente.correo = "nuevo@example.com"
        assert paciente.actualizar() is True
        assert Usuario.buscar(usuario_id).version_credenciales == 1
        with pytest.raises(ValueError):
            usar_token(token, "recuperacion", "Nueva#123")


def test_rf44_cambiar_solo_contacto_no_cierra_sesiones(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        paciente = Paciente.buscar_por_usuario(usuario_id)
        paciente.telefono = "3001112233"
        assert paciente.actualizar() is False
        assert Usuario.buscar(usuario_id).version_credenciales == 0


def test_rf44_cambiar_contrasena_exige_la_actual(app, reloj):
    usuario_id = crear_paciente(app)
    with app.app_context():
        usuario = Usuario.buscar(usuario_id)
        with pytest.raises(ErroresFormulario):
            usuario.cambiar_contrasena("Incorrecta#1", "Nueva#123")
        usuario.cambiar_contrasena(CONTRASENA, "Nueva#123")
        assert Usuario.buscar(usuario_id).version_credenciales == 1
        assert Usuario.autenticar("CC", "1001", "Nueva#123") is not None
