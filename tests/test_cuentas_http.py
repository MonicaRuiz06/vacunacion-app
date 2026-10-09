"""Pruebas de las rutas de cuentas (M02-F/V): formularios, sesiones y permisos."""

import re

from app import create_app
from app.db import get_db
from app.models.usuario import Usuario
from tests.conftest import CONTRASENA, crear_paciente, crear_punto, crear_usuario, ingresar

REGISTRO = {
    "nombre_completo": "Laura Gómez",
    "tipo_documento": "CC",
    "identificacion": "1001",
    "correo": "laura@example.com",
    "fecha_nacimiento": "2000-05-10",
    "contrasena": CONTRASENA,
}


def enlace_del_ultimo_correo(app):
    texto = app.config["CORREOS_ENVIADOS"][-1]["texto"]
    return re.search(r"http://localhost(/\S+)", texto).group(1)


# Registro e ingreso


def test_registro_muestra_formulario(client):
    html = client.get("/registro").get_data(as_text=True)
    assert 'name="identificacion"' in html
    assert 'name="declaracion_responsable"' in html


def test_registro_valido_redirige_al_ingreso(client, reloj):
    respuesta = client.post("/registro", data=REGISTRO)
    assert respuesta.status_code == 303
    assert respuesta.headers["Location"].endswith("/ingresar")


def test_registro_invalido_muestra_errores_por_campo(client, reloj):
    respuesta = client.post("/registro", data={**REGISTRO, "correo": "", "contrasena": "corta"})
    html = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 400
    assert 'id="correo-error"' in html
    assert 'id="contrasena-error"' in html
    assert 'value="Laura Gómez"' in html


def test_registro_de_16_anios_con_declaracion(client, reloj):
    datos = {**REGISTRO, "fecha_nacimiento": "2010-01-01", "declaracion_responsable": "si"}
    assert client.post("/registro", data=datos).status_code == 303


def test_ingreso_correcto_abre_el_perfil(app, client, reloj):
    crear_paciente(app)
    respuesta = ingresar(client)
    assert respuesta.status_code == 303
    assert respuesta.headers["Location"].endswith("/perfil")
    assert "Laura Gómez" in client.get("/perfil").get_data(as_text=True)


def test_ingreso_incorrecto_no_dice_que_fallo(app, client, reloj):
    crear_paciente(app)
    respuesta = ingresar(client, contrasena="Otra#1234")
    assert respuesta.status_code == 400
    assert "Documento o contraseña incorrectos" in respuesta.get_data(as_text=True)


def test_salir_cierra_la_sesion(app, client, reloj):
    crear_paciente(app)
    ingresar(client)
    client.post("/salir")
    assert client.get("/perfil").headers["Location"].endswith("/ingresar")


def test_sesion_de_otra_cuenta_con_el_mismo_id_se_descarta(app, client, reloj):
    # Pasa si se borra la base y una cuenta nueva recibe el id de la anterior.
    admin_id = crear_usuario(app, "administrador")
    with client.session_transaction() as sesion:
        sesion["usuario_id"] = admin_id
        sesion["version"] = 0
        sesion["creado_en"] = "2026-01-01T00:00:00-05:00"
    assert client.get("/usuarios").status_code == 302


def test_perfil_sin_sesion_redirige_al_ingreso(client):
    respuesta = client.get("/perfil")
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/ingresar")


def test_navegacion_cambia_con_la_sesion(app, client, reloj):
    assert "Crear cuenta" in client.get("/").get_data(as_text=True)
    crear_paciente(app)
    ingresar(client)
    html = client.get("/").get_data(as_text=True)
    assert "Mi perfil" in html
    assert "Usuarios" not in html


def test_ingresar_exige_csrf(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "prueba.db")})
    respuesta = app.test_client().post("/ingresar", data={"identificacion": "1001"})
    assert respuesta.status_code == 400


# Perfil (RF-07, RF-44)


def test_paciente_edita_su_perfil(app, client, reloj):
    crear_paciente(app)
    ingresar(client)
    datos = {**REGISTRO, "telefono": "3001112233"}
    datos.pop("contrasena")
    respuesta = client.post("/perfil", data=datos)
    assert respuesta.status_code == 303
    assert "3001112233" in client.get("/perfil").get_data(as_text=True)


def test_perfil_no_muestra_none_en_campos_vacios(app, client, reloj):
    crear_paciente(app)
    ingresar(client)
    assert 'value="None"' not in client.get("/perfil").get_data(as_text=True)


def test_cambiar_correo_cierra_todas_las_sesiones(app, reloj):
    crear_paciente(app)
    primero, segundo = app.test_client(), app.test_client()
    ingresar(primero)
    ingresar(segundo)
    datos = {**REGISTRO, "correo": "nuevo@example.com"}
    datos.pop("contrasena")
    primero.post("/perfil", data=datos)
    assert primero.get("/perfil").status_code == 302
    assert segundo.get("/perfil").status_code == 302


def test_cambiar_contrasena_cierra_todas_las_sesiones(app, reloj):
    crear_paciente(app)
    primero, segundo = app.test_client(), app.test_client()
    ingresar(primero)
    ingresar(segundo)
    respuesta = primero.post("/perfil/contrasena", data={
        "contrasena_actual": CONTRASENA, "contrasena_nueva": "Nueva#123"})
    assert respuesta.status_code == 303
    assert segundo.get("/perfil").status_code == 302
    assert ingresar(segundo, contrasena="Nueva#123").status_code == 303


def test_personal_no_edita_identidad_en_el_perfil(app, client, reloj):
    crear_usuario(app, "vacunador")
    ingresar(client, identificacion="9001")
    assert client.get("/perfil").status_code == 200
    assert client.post("/perfil", data={"nombre_completo": "Otro"}).status_code == 403


# Recuperación (RF-05)


def test_recuperar_responde_igual_si_la_cuenta_no_existe(app, client, reloj):
    crear_paciente(app)
    existe = client.post("/recuperar", data={"tipo_documento": "CC", "identificacion": "1001"})
    no_existe = client.post("/recuperar", data={"tipo_documento": "CC", "identificacion": "999"})
    assert existe.get_data(as_text=True) == no_existe.get_data(as_text=True)
    assert len(app.config["CORREOS_ENVIADOS"]) == 1
    assert app.config["CORREOS_ENVIADOS"][0]["destino"] == "laura@example.com"


def test_enlace_de_recuperacion_cambia_la_contrasena_una_vez(app, client, reloj):
    crear_paciente(app)
    client.post("/recuperar", data={"tipo_documento": "CC", "identificacion": "1001"})
    enlace = enlace_del_ultimo_correo(app)
    assert client.get(enlace).status_code == 200
    assert client.post(enlace, data={"contrasena_nueva": "Nueva#123"}).status_code == 303
    assert client.post(enlace, data={"contrasena_nueva": "Otra#1234"}).status_code == 400
    assert ingresar(client, contrasena="Nueva#123").status_code == 303


# Administración de vacunadores (RF-06)


def test_paciente_no_entra_a_usuarios(app, client, reloj):
    crear_paciente(app)
    ingresar(client)
    assert client.get("/usuarios").status_code == 403
    assert client.post("/usuarios/vacunador", data={}).status_code == 403


def test_admin_invita_vacunador_y_este_establece_su_contrasena(app, client, reloj):
    punto = crear_punto(app)
    crear_usuario(app, "administrador")
    ingresar(client, identificacion="9001")
    respuesta = client.post("/usuarios/vacunador", data={
        "nombre_completo": "Juan Pérez", "tipo_documento": "CC", "identificacion": "7001",
        "correo": "juan@example.com", "puntos": [str(punto)]})
    assert respuesta.status_code == 303
    assert "Juan Pérez" in client.get("/usuarios").get_data(as_text=True)

    vacunador = app.test_client()
    enlace = enlace_del_ultimo_correo(app)
    assert "/invitacion" in enlace
    assert vacunador.post(enlace, data={"contrasena_nueva": "Vacuna#123"}).status_code == 303
    assert ingresar(vacunador, identificacion="7001", contrasena="Vacuna#123").status_code == 303
    assert "Punto Campus" in vacunador.get("/perfil").get_data(as_text=True)


def test_invitar_exige_al_menos_un_punto(app, client, reloj):
    crear_usuario(app, "administrador")
    ingresar(client, identificacion="9001")
    respuesta = client.post("/usuarios/vacunador", data={
        "nombre_completo": "Juan Pérez", "tipo_documento": "CC", "identificacion": "7001",
        "correo": "juan@example.com"})
    assert respuesta.status_code == 400
    with app.app_context():
        assert Usuario.buscar_por_documento("CC", "7001") is None


def test_renovar_invitacion_invalida_la_anterior(app, client, reloj):
    punto = crear_punto(app)
    crear_usuario(app, "administrador")
    ingresar(client, identificacion="9001")
    client.post("/usuarios/vacunador", data={
        "nombre_completo": "Juan Pérez", "tipo_documento": "CC", "identificacion": "7001",
        "correo": "juan@example.com", "puntos": [str(punto)]})
    vieja = enlace_del_ultimo_correo(app)
    with app.app_context():
        vacunador_id = Usuario.buscar_por_documento("CC", "7001").id
    assert client.post(f"/usuarios/{vacunador_id}/invitacion").status_code == 303
    nueva = enlace_del_ultimo_correo(app)
    otro = app.test_client()
    assert otro.post(vieja, data={"contrasena_nueva": "Vacuna#123"}).status_code == 400
    assert otro.post(nueva, data={"contrasena_nueva": "Vacuna#123"}).status_code == 303


def test_admin_asigna_puntos(app, client, reloj):
    campus = crear_punto(app, "Campus")
    centro = crear_punto(app, "Centro")
    crear_usuario(app, "administrador")
    vacunador_id = crear_usuario(app, "vacunador", identificacion="7001", correo="juan@example.com")
    ingresar(client, identificacion="9001")
    assert client.get(f"/usuarios/{vacunador_id}/puntos").status_code == 200
    respuesta = client.post(f"/usuarios/{vacunador_id}/puntos", data={"puntos": [str(campus), str(centro)]})
    assert respuesta.status_code == 303
    with app.app_context():
        puntos = [punto["nombre"] for punto in Usuario.buscar(vacunador_id).puntos()]
        auditoria = get_db().execute("SELECT accion FROM auditoria").fetchall()
    assert puntos == ["Campus", "Centro"]
    assert auditoria[-1]["accion"] == "puntos_asignados"


def test_puntos_de_un_paciente_no_se_asignan(app, client, reloj):
    crear_usuario(app, "administrador")
    paciente_id = crear_paciente(app)
    ingresar(client, identificacion="9001")
    assert client.get(f"/usuarios/{paciente_id}/puntos").status_code == 404


# Administrador inicial


def test_crear_admin_desde_la_consola(app):
    runner = app.test_cli_runner()
    entrada = "Ana Díaz\nCC\n9001\nana@example.com\nAdmin#123\nAdmin#123\n"
    resultado = runner.invoke(args=["crear-admin"], input=entrada)
    assert "Administrador creado" in resultado.output
    with app.app_context():
        assert Usuario.autenticar("CC", "9001", "Admin#123").rol == "administrador"
    segundo = runner.invoke(args=["crear-admin"], input=entrada)
    assert "Ya existe un administrador" in segundo.output
