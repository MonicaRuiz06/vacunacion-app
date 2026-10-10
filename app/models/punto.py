"""Modelo de puntos de vacunación: ubicación, horario y capacidad diaria."""

from app.db import get_db
from app.utils import ErroresFormulario, entero_requerido, hora_requerida


class Punto:
    def __init__(
        self,
        id=None,
        nombre="",
        direccion="",
        municipio=None,
        hora_apertura="",
        hora_cierre="",
        capacidad_diaria=50,
    ):
        self.id = id
        self.nombre = nombre
        self.direccion = direccion
        self.municipio = municipio
        self.hora_apertura = hora_apertura
        self.hora_cierre = hora_cierre
        self.capacidad_diaria = capacidad_diaria

    def validar(self):
        errores = {}
        self.nombre = (self.nombre or "").strip()
        self.direccion = (self.direccion or "").strip()
        self.municipio = (self.municipio or "").strip() or None

        if not self.nombre or len(self.nombre) > 200:
            errores["nombre"] = "Escribe el nombre del punto (máximo 200 caracteres)."
        if not self.direccion or len(self.direccion) > 200:
            errores["direccion"] = "Escribe la dirección (máximo 200 caracteres)."
        try:
            hora_requerida(self.hora_apertura)
        except ValueError:
            errores["hora_apertura"] = "Escribe la hora de apertura (HH:MM)."
        try:
            hora_requerida(self.hora_cierre)
            if "hora_apertura" not in errores and self.hora_cierre <= self.hora_apertura:
                errores["hora_cierre"] = "El cierre debe ser después de la apertura."
        except ValueError:
            errores["hora_cierre"] = "Escribe la hora de cierre (HH:MM)."
        try:
            self.capacidad_diaria = entero_requerido(self.capacidad_diaria)
            if self.capacidad_diaria < 1:
                raise ValueError
        except ValueError:
            errores["capacidad_diaria"] = "La capacidad diaria debe ser un número mayor que 0."

        if errores:
            raise ErroresFormulario(errores)
        return True

    def guardar(self):
        self.validar()
        db = get_db()
        if self.id is None:
            cursor = db.execute(
                "INSERT INTO puntos_vacunacion (nombre, direccion, municipio, hora_apertura,"
                " hora_cierre, capacidad_diaria) VALUES (?, ?, ?, ?, ?, ?)",
                (self.nombre, self.direccion, self.municipio, self.hora_apertura,
                 self.hora_cierre, self.capacidad_diaria),
            )
            self.id = cursor.lastrowid
        else:
            # No se puede cambiar el horario si deja franjas por fuera (RF-13).
            por_fuera = db.execute(
                "SELECT COUNT(*) FROM franjas WHERE punto_id = ?"
                " AND (hora_inicio < ? OR hora_fin > ?)",
                (self.id, self.hora_apertura, self.hora_cierre),
            ).fetchone()[0]
            if por_fuera:
                raise ValueError(
                    f"El nuevo horario deja {por_fuera} franja(s) por fuera. Ajústalas primero."
                )
            db.execute(
                "UPDATE puntos_vacunacion SET nombre = ?, direccion = ?, municipio = ?,"
                " hora_apertura = ?, hora_cierre = ?, capacidad_diaria = ? WHERE id = ?",
                (self.nombre, self.direccion, self.municipio, self.hora_apertura,
                 self.hora_cierre, self.capacidad_diaria, self.id),
            )
        db.commit()
        return self.id

    @staticmethod
    def buscar(punto_id):
        fila = get_db().execute(
            "SELECT * FROM puntos_vacunacion WHERE id = ?", (punto_id,)
        ).fetchone()
        return Punto(**dict(fila)) if fila else None

    @staticmethod
    def listar():
        return get_db().execute("SELECT * FROM puntos_vacunacion ORDER BY nombre").fetchall()
