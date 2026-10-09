"""Configuración común de pruebas: cada prueba usa una base temporal."""

from datetime import datetime

import pytest

from app import create_app
from app.models.paciente import Paciente
from app.models.usuario import Usuario
from app.utils import ZONA_HORARIA

CONTRASENA = "Clave#123"


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "prueba.db"),
        "WTF_CSRF_ENABLED": False,
        "CORREOS_ENVIADOS": [],  # los correos se guardan aquí en lugar de enviarse
    })
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def reloj(monkeypatch):
    """Fija la hora a 2026-10-08 12:00 en Bogotá. Cambiar reloj["ahora"] la mueve."""
    estado = {"ahora": datetime(2026, 10, 8, 12, 0, tzinfo=ZONA_HORARIA)}

    def ahora_fija():
        return estado["ahora"]

    for modulo in ("app.utils", "app.models.usuario", "app.models.auditoria"):
        monkeypatch.setattr(f"{modulo}.ahora", ahora_fija)
    return estado


def datos_paciente(**cambios):
    datos = {
        "nombre_completo": "Laura Gómez",
        "tipo_documento": "CC",
        "identificacion": "1001",
        "correo": "laura@example.com",
        "fecha_nacimiento": "2000-05-10",
    }
    datos.update(cambios)
    return datos


def crear_paciente(app, contrasena=CONTRASENA, **cambios):
    """Registra un paciente y devuelve el id de su usuario."""
    with app.app_context():
        paciente = Paciente(**datos_paciente(**cambios))
        paciente.guardar(contrasena)
        return paciente.usuario_id


def crear_usuario(app, rol, contrasena=CONTRASENA, **cambios):
    """Crea una cuenta de personal y devuelve su id."""
    datos = {
        "nombre_completo": "Ana Díaz",
        "tipo_documento": "CC",
        "identificacion": "9001",
        "correo": "ana@example.com",
        "rol": rol,
    }
    datos.update(cambios)
    with app.app_context():
        usuario = Usuario(**datos)
        usuario.guardar(contrasena)
        return usuario.id


def crear_punto(app, nombre="Punto Campus"):
    from app.db import get_db

    with app.app_context():
        db = get_db()
        cursor = db.execute(
            "INSERT INTO puntos_vacunacion (nombre, direccion, hora_apertura, hora_cierre)"
            " VALUES (?, 'Calle 5', '08:00', '16:00')",
            (nombre,),
        )
        db.commit()
        return cursor.lastrowid


def ingresar(client, identificacion="1001", contrasena=CONTRASENA, tipo_documento="CC"):
    return client.post("/ingresar", data={
        "tipo_documento": tipo_documento,
        "identificacion": identificacion,
        "contrasena": contrasena,
    })
