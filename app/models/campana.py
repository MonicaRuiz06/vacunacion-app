"""Modelo de campañas: datos, puntos y vacunas participantes, y su estado.

Estados: borrador → publicada ⇄ pausada → finalizada (RF-09, RF-10).
"""

from app.db import get_db
from app.models.auditoria import registrar_auditoria
from app.utils import ErroresFormulario, ahora, fecha_requerida


def hoy():
    return ahora().date().isoformat()


def ids_validos(valores, tabla):
    """Convierte ids elegidos en enteros que existan en la tabla indicada."""
    db = get_db()
    ids = []
    for valor in valores or []:
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            continue
        if db.execute(f"SELECT 1 FROM {tabla} WHERE id = ?", (numero,)).fetchone():
            ids.append(numero)
    return sorted(set(ids))


class Campana:
    def __init__(
        self,
        id=None,
        nombre="",
        descripcion="",
        fecha_inicio="",
        fecha_fin="",
        estado="borrador",
        puntos_ids=None,
        vacunas_ids=None,
    ):
        self.id = id
        self.nombre = nombre
        self.descripcion = descripcion
        self.fecha_inicio = fecha_inicio
        self.fecha_fin = fecha_fin
        self.estado = estado
        self.puntos_ids = puntos_ids or []
        self.vacunas_ids = vacunas_ids or []

    def validar(self):
        errores = {}
        self.nombre = (self.nombre or "").strip()
        self.descripcion = (self.descripcion or "").strip()

        if not self.nombre or len(self.nombre) > 200:
            errores["nombre"] = "Escribe el nombre de la campaña (máximo 200 caracteres)."
        if not self.descripcion or len(self.descripcion) > 2000:
            errores["descripcion"] = "Escribe una descripción (máximo 2000 caracteres)."
        try:
            fecha_requerida(self.fecha_inicio)
            # Una campaña nueva no puede empezar en el pasado. Al editar no se
            # exige: una campaña que ya empezó tiene su inicio antes de hoy.
            if self.id is None and self.fecha_inicio < hoy():
                errores["fecha_inicio"] = "La fecha de inicio no puede ser anterior a hoy."
        except ValueError:
            errores["fecha_inicio"] = "Escribe una fecha de inicio válida."
        try:
            fecha_requerida(self.fecha_fin)
            if "fecha_inicio" not in errores and self.fecha_fin < self.fecha_inicio:
                errores["fecha_fin"] = "La fecha final no puede ser anterior a la inicial."
        except ValueError:
            errores["fecha_fin"] = "Escribe una fecha final válida."
        self.puntos_ids = ids_validos(self.puntos_ids, "puntos_vacunacion")
        self.vacunas_ids = ids_validos(self.vacunas_ids, "vacunas")

        if errores:
            raise ErroresFormulario(errores)
        return True

    def citas_por_fuera(self):
        """Citas activas que quedarían fuera de la configuración nueva (RF-13)."""
        if self.id is None:
            return 0
        puntos = ",".join(str(punto_id) for punto_id in self.puntos_ids) or "0"
        vacunas = ",".join(str(vacuna_id) for vacuna_id in self.vacunas_ids) or "0"
        # Los ids vienen de ids_validos(), así que son enteros seguros.
        return get_db().execute(
            "SELECT COUNT(*) FROM citas c JOIN franjas f ON f.id = c.franja_id"
            " WHERE c.campana_id = ? AND c.estado IN ('reservada', 'presente')"
            f" AND (c.vacuna_id NOT IN ({vacunas}) OR f.punto_id NOT IN ({puntos})"
            "      OR f.fecha < ? OR f.fecha > ?)",
            (self.id, self.fecha_inicio, self.fecha_fin),
        ).fetchone()[0]

    def guardar(self, actor_id):
        """Crea la campaña en borrador o guarda sus cambios."""
        self.validar()
        afectadas = self.citas_por_fuera()
        if afectadas:
            # En M08 este rechazo se reemplaza por cancelar con motivo y avisar.
            raise ValueError(
                f"El cambio deja {afectadas} cita(s) activa(s) fuera de la campaña. "
                "Por ahora no se puede aplicar."
            )
        db = get_db()
        with db:
            if self.id is None:
                cursor = db.execute(
                    "INSERT INTO campanas (nombre, descripcion, fecha_inicio, fecha_fin, estado)"
                    " VALUES (?, ?, ?, ?, 'borrador')",
                    (self.nombre, self.descripcion, self.fecha_inicio, self.fecha_fin),
                )
                self.id = cursor.lastrowid
                accion = "campana_creada"
            else:
                db.execute(
                    "UPDATE campanas SET nombre = ?, descripcion = ?, fecha_inicio = ?,"
                    " fecha_fin = ? WHERE id = ?",
                    (self.nombre, self.descripcion, self.fecha_inicio, self.fecha_fin, self.id),
                )
                accion = "campana_editada"
            db.execute("DELETE FROM campana_puntos WHERE campana_id = ?", (self.id,))
            db.execute("DELETE FROM campana_vacunas WHERE campana_id = ?", (self.id,))
            db.executemany("INSERT INTO campana_puntos (campana_id, punto_id) VALUES (?, ?)",
                           [(self.id, punto_id) for punto_id in self.puntos_ids])
            db.executemany("INSERT INTO campana_vacunas (campana_id, vacuna_id) VALUES (?, ?)",
                           [(self.id, vacuna_id) for vacuna_id in self.vacunas_ids])
            registrar_auditoria(actor_id, accion, "campanas", self.id, {
                "nombre": self.nombre, "fechas": [self.fecha_inicio, self.fecha_fin],
                "puntos": self.puntos_ids, "vacunas": self.vacunas_ids,
            })
        return self.id

    def tiene_franja_valida(self):
        """Hay al menos una franja de sus puntos dentro de sus fechas."""
        return get_db().execute(
            "SELECT 1 FROM franjas f JOIN campana_puntos cp ON cp.punto_id = f.punto_id"
            " WHERE cp.campana_id = ? AND f.fecha BETWEEN ? AND ?",
            (self.id, self.fecha_inicio, self.fecha_fin),
        ).fetchone() is not None

    def cambiar_estado(self, nuevo, actor_id):
        db = get_db()
        with db:
            db.execute("UPDATE campanas SET estado = ? WHERE id = ?", (nuevo, self.id))
            registrar_auditoria(actor_id, f"campana_{nuevo}", "campanas", self.id,
                                {"antes": self.estado, "despues": nuevo})
        self.estado = nuevo

    def publicar(self, actor_id):
        """Publica una campaña completa (RF-09)."""
        if self.estado != "borrador":
            raise ValueError("Solo se puede publicar una campaña en borrador.")
        if not self.puntos_ids:
            raise ValueError("Para publicar, la campaña necesita al menos un punto.")
        if not self.vacunas_ids:
            raise ValueError("Para publicar, la campaña necesita al menos una vacuna.")
        if self.fecha_fin < hoy():
            raise ValueError("La campaña ya terminó; no se puede publicar.")
        if not self.tiene_franja_valida():
            raise ValueError("Para publicar, crea al menos una franja en sus puntos y fechas.")
        self.cambiar_estado("publicada", actor_id)

    def pausar(self, actor_id):
        """Pausa nuevas reservas; las citas existentes se conservan (RF-10)."""
        if self.estado != "publicada":
            raise ValueError("Solo se puede pausar una campaña publicada.")
        self.cambiar_estado("pausada", actor_id)

    def reanudar(self, actor_id):
        if self.estado != "pausada" or self.fecha_fin < hoy():
            raise ValueError("Solo se puede reanudar una campaña pausada que no haya terminado.")
        self.cambiar_estado("publicada", actor_id)

    @staticmethod
    def finalizar_vencidas():
        """Marca como finalizadas las campañas cuya fecha final ya pasó (RF-09)."""
        db = get_db()
        db.execute(
            "UPDATE campanas SET estado = 'finalizada'"
            " WHERE estado IN ('publicada', 'pausada') AND fecha_fin < ?",
            (hoy(),),
        )
        db.commit()

    @staticmethod
    def buscar(campana_id):
        db = get_db()
        fila = db.execute("SELECT * FROM campanas WHERE id = ?", (campana_id,)).fetchone()
        if fila is None:
            return None
        campana = Campana(**dict(fila))
        campana.puntos_ids = [f[0] for f in db.execute(
            "SELECT punto_id FROM campana_puntos WHERE campana_id = ? ORDER BY punto_id",
            (campana_id,))]
        campana.vacunas_ids = [f[0] for f in db.execute(
            "SELECT vacuna_id FROM campana_vacunas WHERE campana_id = ? ORDER BY vacuna_id",
            (campana_id,))]
        return campana

    @staticmethod
    def listar(solo_publicadas=False):
        consulta = "SELECT id FROM campanas"
        if solo_publicadas:
            consulta += " WHERE estado = 'publicada'"
        consulta += " ORDER BY fecha_inicio, nombre"
        return [Campana.buscar(fila["id"]) for fila in get_db().execute(consulta)]

    def puntos(self):
        return get_db().execute(
            "SELECT p.* FROM puntos_vacunacion p JOIN campana_puntos cp ON cp.punto_id = p.id"
            " WHERE cp.campana_id = ? ORDER BY p.nombre", (self.id,)).fetchall()

    def vacunas(self):
        return get_db().execute(
            "SELECT v.* FROM vacunas v JOIN campana_vacunas cv ON cv.vacuna_id = v.id"
            " WHERE cv.campana_id = ? ORDER BY v.nombre", (self.id,)).fetchall()

    def franjas(self):
        """Franjas de sus puntos dentro de sus fechas."""
        return get_db().execute(
            "SELECT f.*, p.nombre AS punto FROM franjas f"
            " JOIN campana_puntos cp ON cp.punto_id = f.punto_id"
            " JOIN puntos_vacunacion p ON p.id = f.punto_id"
            " WHERE cp.campana_id = ? AND f.fecha BETWEEN ? AND ?"
            " ORDER BY f.fecha, p.nombre, f.hora_inicio",
            (self.id, self.fecha_inicio, self.fecha_fin)).fetchall()
