"""Pruebas de la base técnica (M00)."""

import pytest

from app import create_app
from app.db import get_db
from app.models.paciente import Paciente
from app.utils import ahora, entero_requerido, fecha_requerida, texto_requerido

TABLAS_INICIALES = {
    "pacientes",
    "vacunas",
    "puntos_vacunacion",
    "inventarios_biologicos",
    "citas",
    "dosis_aplicadas",
}


def test_inicio_responde(client):
    respuesta = client.get("/")
    assert respuesta.status_code == 200
    assert "Sistema de Gestión de Campañas de Vacunación" in respuesta.get_data(as_text=True)


def test_crea_las_tablas_del_esquema(app):
    with app.app_context():
        filas = get_db().execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tablas = {fila["name"] for fila in filas}
    assert TABLAS_INICIALES <= tablas


def test_claves_foraneas_activas(app):
    with app.app_context():
        assert get_db().execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_arrancar_dos_veces_conserva_los_datos(tmp_path):
    config = {"TESTING": True, "DATABASE": str(tmp_path / "prueba.db")}
    app = create_app(config)
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO vacunas (nombre, lote, fecha_vencimiento) VALUES ('Influenza', 'L1', '2027-01-01')")
        db.commit()
    app = create_app(config)
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM vacunas").fetchone()[0] == 1


def test_formulario_sin_csrf_se_rechaza(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "prueba.db")})
    app.add_url_rule("/formulario", "formulario", lambda: "ok", methods=["POST"])
    cliente = app.test_client()
    assert cliente.post("/formulario").status_code == 400


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_texto_requerido_rechaza_vacios(valor):
    with pytest.raises(ValueError):
        texto_requerido(valor)


def test_texto_requerido_quita_espacios():
    assert texto_requerido("  Ana  ") == "Ana"


@pytest.mark.parametrize("valor", [None, "", "2026-02-30", "14/11/2026"])
def test_fecha_requerida_rechaza_invalidas(valor):
    with pytest.raises(ValueError):
        fecha_requerida(valor)


def test_fecha_requerida_acepta_iso():
    assert fecha_requerida("2026-11-14") == "2026-11-14"


@pytest.mark.parametrize("valor", [None, "", "dos", "1.5"])
def test_entero_requerido_rechaza_no_enteros(valor):
    with pytest.raises(ValueError):
        entero_requerido(valor)


def test_entero_requerido_convierte():
    assert entero_requerido("3") == 3


def test_ahora_usa_hora_de_bogota():
    assert ahora().utcoffset().total_seconds() == -5 * 3600


def test_paciente_valida_campos_obligatorios():
    assert Paciente(nombre_completo="Ana", identificacion="123", fecha_nacimiento="2000-01-01").validar()
    with pytest.raises(ValueError):
        Paciente(nombre_completo="", identificacion="123", fecha_nacimiento="2000-01-01").validar()
