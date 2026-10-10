"""Modelo de vacunas: el producto, independiente de sus lotes."""

from app.db import get_db
from app.utils import ErroresFormulario, entero_requerido


class Vacuna:
    def __init__(self, id=None, nombre="", fabricante=None, dosis_requeridas=1):
        self.id = id
        self.nombre = nombre
        self.fabricante = fabricante
        self.dosis_requeridas = dosis_requeridas

    def validar(self):
        errores = {}
        self.nombre = (self.nombre or "").strip()
        self.fabricante = (self.fabricante or "").strip() or None

        if not self.nombre or len(self.nombre) > 200:
            errores["nombre"] = "Escribe el nombre de la vacuna (máximo 200 caracteres)."
        if self.fabricante and len(self.fabricante) > 200:
            errores["fabricante"] = "Máximo 200 caracteres."
        try:
            self.dosis_requeridas = entero_requerido(self.dosis_requeridas)
            if self.dosis_requeridas < 1:
                raise ValueError
        except ValueError:
            errores["dosis_requeridas"] = "Las dosis requeridas deben ser un número mayor que 0."

        if errores:
            raise ErroresFormulario(errores)
        return True

    def guardar(self):
        self.validar()
        db = get_db()
        if self.id is None:
            cursor = db.execute(
                "INSERT INTO vacunas (nombre, fabricante, dosis_requeridas) VALUES (?, ?, ?)",
                (self.nombre, self.fabricante, self.dosis_requeridas),
            )
            self.id = cursor.lastrowid
        else:
            # Las dosis no pueden quedar por debajo de las ya aplicadas (RF-29).
            mayor = db.execute(
                "SELECT MAX(numero_dosis) FROM dosis_aplicadas WHERE vacuna_id = ?", (self.id,)
            ).fetchone()[0]
            if mayor and self.dosis_requeridas < mayor:
                raise ErroresFormulario({
                    "dosis_requeridas": f"Ya hay aplicaciones de la dosis {mayor}; no puede ser menor."
                })
            db.execute(
                "UPDATE vacunas SET nombre = ?, fabricante = ?, dosis_requeridas = ? WHERE id = ?",
                (self.nombre, self.fabricante, self.dosis_requeridas, self.id),
            )
        db.commit()
        return self.id

    @staticmethod
    def buscar(vacuna_id):
        fila = get_db().execute("SELECT * FROM vacunas WHERE id = ?", (vacuna_id,)).fetchone()
        return Vacuna(**dict(fila)) if fila else None

    @staticmethod
    def listar():
        return get_db().execute("SELECT * FROM vacunas ORDER BY nombre").fetchall()
