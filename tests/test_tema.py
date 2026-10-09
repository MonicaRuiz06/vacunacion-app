"""Pruebas del tema claro/noche y la navegación por rol (M03)."""

from tests.conftest import crear_paciente, crear_usuario, ingresar


def test_sin_preferencia_sigue_al_sistema(client):
    assert 'data-tema="sistema"' in client.get("/").get_data(as_text=True)


def test_elegir_modo_noche_guarda_cookie_y_vuelve(client):
    respuesta = client.post("/tema", data={"tema": "oscuro", "volver": "/registro"})
    assert respuesta.status_code == 303
    assert respuesta.headers["Location"].endswith("/registro")
    assert "tema=oscuro" in respuesta.headers["Set-Cookie"]
    assert "HttpOnly" in respuesta.headers["Set-Cookie"]
    assert 'data-tema="oscuro"' in client.get("/").get_data(as_text=True)


def test_volver_a_tema_del_sistema_borra_la_cookie(client):
    client.post("/tema", data={"tema": "oscuro", "volver": "/"})
    client.post("/tema", data={"tema": "sistema", "volver": "/"})
    assert 'data-tema="sistema"' in client.get("/").get_data(as_text=True)


def test_tema_invalido_se_rechaza(client):
    assert client.post("/tema", data={"tema": "rosado", "volver": "/"}).status_code == 400


def test_cookie_manipulada_se_ignora(client):
    client.set_cookie("tema", "<script>")
    html = client.get("/").get_data(as_text=True)
    assert 'data-tema="sistema"' in html
    assert "<script>" not in html


def test_volver_solo_acepta_rutas_internas(client):
    for destino in ("https://ejemplo.com", "//ejemplo.com", "javascript:alert(1)", ""):
        respuesta = client.post("/tema", data={"tema": "claro", "volver": destino})
        assert respuesta.headers["Location"].endswith("/")
        assert "ejemplo" not in respuesta.headers["Location"]


def test_boton_de_tema_en_la_cabecera(client):
    html = client.get("/").get_data(as_text=True)
    assert "Modo noche" in html
    assert "Modo claro" in html


def test_navegacion_del_administrador(app, client, reloj):
    crear_usuario(app, "administrador")
    ingresar(client, identificacion="9001")
    html = client.get("/usuarios").get_data(as_text=True)
    assert 'href="/usuarios" aria-current="page"' in html
    assert "Administrador" in html


def test_navegacion_del_vacunador_no_muestra_usuarios(app, client, reloj):
    crear_usuario(app, "vacunador")
    ingresar(client, identificacion="9001")
    html = client.get("/perfil").get_data(as_text=True)
    assert 'href="/usuarios"' not in html
    assert "Vacunador" in html


def test_menu_oculto_no_reemplaza_el_permiso_del_servidor(app, client, reloj):
    crear_paciente(app)
    ingresar(client)
    assert 'href="/usuarios"' not in client.get("/").get_data(as_text=True)
    assert client.get("/usuarios").status_code == 403
