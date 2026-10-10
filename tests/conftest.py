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

    for modulo in ("app.utils", "app.models.usuario", "app.models.auditoria",
                   "app.models.lote", "app.models.campana", "app.models.inventario"):
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


def crear_vacuna(app, nombre="Influenza", dosis_requeridas=1):
    from app.models.vacuna import Vacuna

    with app.app_context():
        vacuna = Vacuna(nombre=nombre, fabricante="Laboratorio Demo", dosis_requeridas=dosis_requeridas)
        return vacuna.guardar()


def crear_lote(app, vacuna_id, codigo="L-2041", fecha_vencimiento="2026-11-30"):
    from app.models.lote import Lote

    with app.app_context():
        return Lote(vacuna_id=vacuna_id, codigo=codigo, fecha_vencimiento=fecha_vencimiento).guardar()


def crear_franja(app, punto_id, fecha="2026-11-14", hora_inicio="09:00", hora_fin="09:30", cupos=5):
    from app.models.franja import Franja

    with app.app_context():
        franja = Franja(punto_id=punto_id, fecha=fecha, hora_inicio=hora_inicio,
                        hora_fin=hora_fin, cupos=cupos)
        return franja.guardar()


def crear_campana(app, admin_id, puntos=(), vacunas=(), nombre="Jornada de bienestar",
                  fecha_inicio="2026-11-10", fecha_fin="2026-11-20"):
    from app.models.campana import Campana

    with app.app_context():
        campana = Campana(nombre=nombre, descripcion="Campaña ficticia", fecha_inicio=fecha_inicio,
                          fecha_fin=fecha_fin, puntos_ids=list(puntos), vacunas_ids=list(vacunas))
        return campana.guardar(admin_id)


def crear_cita(app, usuario_paciente_id, campana_id, vacuna_id, franja_id, estado="reservada"):
    """Inserta una cita directamente (las reservas llegan en M07)."""
    from app.db import get_db

    with app.app_context():
        db = get_db()
        paciente_id = db.execute(
            "SELECT id FROM pacientes WHERE usuario_id = ?", (usuario_paciente_id,)
        ).fetchone()[0]
        cursor = db.execute(
            "INSERT INTO citas (paciente_id, campana_id, vacuna_id, franja_id, estado, creado_en)"
            " VALUES (?, ?, ?, ?, ?, '2026-10-08T12:00:00-05:00')",
            (paciente_id, campana_id, vacuna_id, franja_id, estado),
        )
        db.commit()
        return cursor.lastrowid


def ingresar(client, identificacion="1001", contrasena=CONTRASENA, tipo_documento="CC"):
    return client.post("/ingresar", data={
        "tipo_documento": tipo_documento,
        "identificacion": identificacion,
        "contrasena": contrasena,
    })
