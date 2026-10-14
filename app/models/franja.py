"""Modelo de franjas: horario de atención de un punto en una fecha, con cupos.

Los cupos de una franja se comparten entre todas las campañas (RF-11).
"""

from app.db import get_db
from app.models.punto import Punto
from app.utils import ErroresFormulario, entero_requerido, fecha_requerida, hora_requerida

# Estados de cita que ocupan cupo (RF-41). Cancelada y no asistió lo liberan.
ESTADOS_QUE_OCUPAN = ("reservada", "presente", "aplicada", "no_aplicada", "registro_anulado")


def cupos_validos(valor):
    """Convierte los cupos a entero mayor que 0, o lanza ValueError."""
    cupos = entero_requerido(valor)
    if cupos < 1:
        raise ValueError
    return cupos


class Franja:
    def __init__(self, id=None, punto_id=None, fecha="", hora_inicio="", hora_fin="", cupos=1):
        self.id = id
        self.punto_id = punto_id
        self.fecha = fecha
        self.hora_inicio = hora_inicio
        self.hora_fin = hora_fin
        self.cupos = cupos

    def validar(self):
        errores = {}
        punto = Punto.buscar(self.punto_id)
        if punto is None:
            errores["punto_id"] = "Elige un punto de vacunación."
        try:
            fecha_requerida(self.fecha)
        except ValueError:
            errores["fecha"] = "Escribe una fecha válida."
        try:
            hora_requerida(self.hora_inicio)
            hora_requerida(self.hora_fin)
            if self.hora_fin <= self.hora_inicio:
                errores["hora_fin"] = "La hora final debe ser después de la inicial."
            elif punto and self.hora_inicio < punto.hora_apertura:
                errores["hora_inicio"] = f"El punto abre a las {punto.hora_apertura}."
            elif punto and self.hora_fin > punto.hora_cierre:
                errores["hora_fin"] = f"El punto cierra a las {punto.hora_cierre}."
        except ValueError:
            errores["hora_inicio"] = "Escribe las horas en formato HH:MM."
        try:
            self.cupos = cupos_validos(self.cupos)
        except ValueError:
            errores["cupos"] = "Los cupos deben ser un número mayor que 0."

        if not errores and self.se_cruza():
            errores["hora_inicio"] = "Esta franja se cruza con otra del mismo punto y fecha."
        if errores:
            raise ErroresFormulario(errores)
        return True

    def se_cruza(self):
        """True si otra franja del mismo punto y fecha se superpone con esta."""
        return get_db().execute(
            "SELECT 1 FROM franjas WHERE punto_id = ? AND fecha = ? AND id != ?"
            " AND hora_inicio < ? AND hora_fin > ?",
            (self.punto_id, self.fecha, self.id or 0, self.hora_fin, self.hora_inicio),
        ).fetchone() is not None

    def guardar(self):
        """Crea la franja. Después solo pueden cambiar sus cupos."""
        self.validar()
        db = get_db()
        cursor = db.execute(
            "INSERT INTO franjas (punto_id, fecha, hora_inicio, hora_fin, cupos) VALUES (?, ?, ?, ?, ?)",
            (self.punto_id, self.fecha, self.hora_inicio, self.hora_fin, self.cupos),
        )
        db.commit()
        self.id = cursor.lastrowid
        return self.id

    def ocupados(self):
        """Citas de cualquier campaña que ocupan cupo en esta franja."""
        marcas = ", ".join("?" for _ in ESTADOS_QUE_OCUPAN)
        return get_db().execute(
            f"SELECT COUNT(*) FROM citas WHERE franja_id = ? AND estado IN ({marcas})",
            (self.id, *ESTADOS_QUE_OCUPAN),
        ).fetchone()[0]

    def cambiar_cupos(self, cupos):
        """Cambia los cupos sin bajar de las citas que ya los ocupan (RF-12)."""
        try:
            cupos = cupos_validos(cupos)
        except ValueError:
            raise ValueError("Los cupos deben ser un número mayor que 0.")
        ocupados = self.ocupados()
        if cupos < ocupados:
            raise ValueError(f"Hay {ocupados} citas en esta franja; los cupos no pueden ser menos.")
        db = get_db()
        db.execute("UPDATE franjas SET cupos = ? WHERE id = ?", (cupos, self.id))
        db.commit()
        self.cupos = cupos

    @staticmethod
    def buscar(franja_id):
        fila = get_db().execute("SELECT * FROM franjas WHERE id = ?", (franja_id,)).fetchone()
        return Franja(**dict(fila)) if fila else None

    @staticmethod
    def listar(punto_id=None, fecha=None):
        """Franjas con el nombre del punto y sus cupos ocupados, filtrables."""
        marcas = ", ".join("?" for _ in ESTADOS_QUE_OCUPAN)
        consulta = (
            "SELECT f.*, p.nombre AS punto,"
            f" (SELECT COUNT(*) FROM citas c WHERE c.franja_id = f.id AND c.estado IN ({marcas}))"
            " AS ocupados"
            " FROM franjas f JOIN puntos_vacunacion p ON p.id = f.punto_id WHERE 1 = 1"
        )
        parametros = list(ESTADOS_QUE_OCUPAN)
        if punto_id:
            consulta += " AND f.punto_id = ?"
            parametros.append(punto_id)
        if fecha:
            consulta += " AND f.fecha = ?"
            parametros.append(fecha)
        consulta += " ORDER BY f.fecha, p.nombre, f.hora_inicio"
        return get_db().execute(consulta, parametros).fetchall()
