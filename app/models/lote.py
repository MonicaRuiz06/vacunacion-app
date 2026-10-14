"""Modelo de lotes: cada lote pertenece a una vacuna y tiene vencimiento."""

import sqlite3

from app.db import get_db
from app.utils import ErroresFormulario, ahora, fecha_requerida


class Lote:
    def __init__(self, id=None, vacuna_id=None, codigo="", fecha_vencimiento=""):
        self.id = id
        self.vacuna_id = vacuna_id
        self.codigo = codigo
        self.fecha_vencimiento = fecha_vencimiento

    def validar(self):
        errores = {}
        self.codigo = (self.codigo or "").strip()

        if not self.codigo or len(self.codigo) > 40:
            errores["codigo"] = "Escribe el código del lote (máximo 40 caracteres)."
        try:
            fecha_requerida(self.fecha_vencimiento)
        except ValueError:
            errores["fecha_vencimiento"] = "Escribe una fecha de vencimiento válida."
        if not get_db().execute("SELECT 1 FROM vacunas WHERE id = ?", (self.vacuna_id,)).fetchone():
            errores["vacuna_id"] = "Elige una vacuna."

        if errores:
            raise ErroresFormulario(errores)
        return True

    def guardar(self):
        """Crea el lote. Los lotes no se editan para no alterar la historia."""
        self.validar()
        db = get_db()
        try:
            cursor = db.execute(
                "INSERT INTO lotes (vacuna_id, codigo, fecha_vencimiento) VALUES (?, ?, ?)",
                (self.vacuna_id, self.codigo, self.fecha_vencimiento),
            )
            db.commit()
        except sqlite3.IntegrityError:
            raise ErroresFormulario({"codigo": "Esta vacuna ya tiene un lote con ese código."})
        self.id = cursor.lastrowid
        return self.id

    def vencido(self):
        """El lote sirve hasta su fecha de vencimiento, inclusive (RF-25)."""
        return self.fecha_vencimiento < ahora().date().isoformat()

    @staticmethod
    def listar():
        """Lotes con el nombre de su vacuna; vencido es 1 desde el día siguiente al vencimiento."""
        return get_db().execute(
            "SELECT l.*, v.nombre AS vacuna, l.fecha_vencimiento < ? AS vencido"
            " FROM lotes l JOIN vacunas v ON v.id = l.vacuna_id"
            " ORDER BY v.nombre, l.fecha_vencimiento",
            (ahora().date().isoformat(),),
        ).fetchall()

    @staticmethod
    def opciones():
        """Lotes para una lista desplegable: «Vacuna · código · vence fecha»."""
        return get_db().execute(
            "SELECT l.id, v.nombre || ' · ' || l.codigo || ' · vence ' || l.fecha_vencimiento"
            " AS nombre FROM lotes l JOIN vacunas v ON v.id = l.vacuna_id"
            " ORDER BY v.nombre, l.fecha_vencimiento"
        ).fetchall()
