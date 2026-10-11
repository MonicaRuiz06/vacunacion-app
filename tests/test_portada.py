"""Pruebas de la cabecera (tema, avatar) y de la página de inicio (ajuste de M03)."""

from app.models.campana import Campana
from app.models.usuario import Usuario
from tests.conftest import (
    crear_campana,
    crear_franja,
    crear_paciente,
    crear_punto,
    crear_usuario,
    crear_vacuna,
    ingresar,
)


def menu_principal(html):
    """Solo el bloque del menú de píldoras."""
    inicio = html.index('<nav class="menu"')
    return html[inicio:html.index("</nav>", inicio)]


# Cabecera


def test_boton_de_tema_es_un_icono_con_nombre_accesible(client):
    html = client.get("/").get_data(as_text=True)
    assert 'aria-label="Modo noche"' in html
    assert 'aria-label="Modo claro"' in html
    assert html.count('<svg class="icono"') >= 2


def test_avatar_con_iniciales_y_menu_de_cuenta(app, client, reloj):
    crear_paciente(app)  # Laura Gómez
    ingresar(client)
    html = client.get("/").get_data(as_text=True)
    assert '<summary class="avatar"' in html
    assert ">LG<" in html
    cuenta = html[html.index('class="menu-cuenta"'):]
    assert "Mi perfil" in cuenta
    assert ">Salir</button>" in cuenta
    assert "Mi perfil" not in menu_principal(html)
    assert "Salir" not in menu_principal(html)


def test_iniciales_del_usuario(app, reloj):
    with app.app_context():
        assert Usuario(nombre_completo="Ana Díaz").iniciales() == "AD"
        assert Usuario(nombre_completo="  juan  ").iniciales() == "J"


# Inicio sin sesión (portada)


def test_portada_muestra_campanas_publicadas_y_puntos(app, client, reloj):
    admin = crear_usuario(app, "administrador")
    punto = crear_punto(app, "Punto Campus")
    vacuna = crear_vacuna(app, nombre="Influenza")
    crear_franja(app, punto)
    publicada = crear_campana(app, admin, puntos=[punto], vacunas=[vacuna], nombre="Jornada abierta")
    crear_campana(app, admin, nombre="Jornada en borrador")
    with app.app_context():
        Campana.buscar(publicada).publicar(admin)
    html = client.get("/").get_data(as_text=True)
    assert "Sistema de Gestión de Campañas de Vacunación" in html
    assert "Jornada abierta" in html
    assert "Jornada en borrador" not in html
    assert "Punto Campus" in html
    assert "Influenza" in html
    assert "<details" in html  # preguntas frecuentes desplegables
    assert 'href="/registro"' in html


def test_portada_sin_campanas_lo_dice(client):
    assert "Pronto publicaremos nuevas campañas" in client.get("/").get_data(as_text=True)


# Inicio con sesión (accesos según el rol)


def test_inicio_del_paciente(app, client, reloj):
    crear_paciente(app)
    ingresar(client)
    html = client.get("/").get_data(as_text=True)
    assert "Hola, Laura" in html
    assert "Reservar una cita" in html
    assert "Inventario" not in html


def test_inicio_del_administrador(app, client, reloj):
    crear_usuario(app, "administrador")
    ingresar(client, identificacion="9001")
    html = client.get("/").get_data(as_text=True)
    assert "Hola, Ana" in html
    for acceso in ("Campañas", "Agenda", "Inventario", "Usuarios"):
        assert acceso in html
