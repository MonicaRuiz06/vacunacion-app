"""Modelo de inventario: existencias por punto y lote, y disponibilidad de dosis.

Existencia física (unidades en el punto) y disponibilidad para reservar son
cosas distintas: cada cita reservada o presente aparta una dosis de su vacuna
en su punto, sin asignarle lote (RF-14).
"""

import sqlite3

from app.db import get_db
from app.utils import ErroresFormulario, ahora, entero_requerido

ESTADOS_QUE_RESERVAN = ("reservada", "presente")


def hoy():
    return ahora().date().isoformat()


def validar_motivo(motivo, errores):
    motivo = (motivo or "").strip()
    if not motivo or len(motivo) > 1000:
        errores["motivo"] = "Escribe el motivo (máximo 1000 caracteres)."
    return motivo


def registrar_entrada(punto_id, lote_id, cantidad, motivo, usuario_id, clave=None):
    """Registra unidades recibidas de un lote en un punto (RF-23).

    Devuelve el id del inventario. Si la clave del formulario ya se usó, no
    registra nada otra vez.
    """
    db = get_db()
    errores = {}
    if not db.execute("SELECT 1 FROM puntos_vacunacion WHERE id = ?", (punto_id,)).fetchone():
        errores["punto_id"] = "Elige un punto de vacunación."
    if not db.execute("SELECT 1 FROM lotes WHERE id = ?", (lote_id,)).fetchone():
        errores["lote_id"] = "Elige un lote."
    try:
        cantidad = entero_requerido(cantidad)
        if cantidad < 1:
            raise ValueError
    except ValueError:
        errores["cantidad"] = "La cantidad debe ser un número mayor que 0."
    motivo = validar_motivo(motivo, errores)
    if errores:
        raise ErroresFormulario(errores)

    db.execute(
        "INSERT INTO inventarios_biologicos (punto_id, lote_id) VALUES (?, ?)"
        " ON CONFLICT (punto_id, lote_id) DO NOTHING",
        (punto_id, lote_id),
    )
    db.commit()
    fila = db.execute(
        "SELECT * FROM inventarios_biologicos WHERE punto_id = ? AND lote_id = ?",
        (punto_id, lote_id),
    ).fetchone()
    inventario = Inventario(**dict(fila))
    inventario.mover(cantidad, "entrada", motivo, usuario_id, clave)
    return inventario.id


def mover_saldo(inventario_id, cantidad, tipo, motivo, usuario_id, clave=None):
    """Suma o resta unidades y registra el movimiento. No hace commit.

    El UPDATE solo se aplica si el saldo no queda negativo, así dos cambios
    simultáneos no pueden gastar la misma unidad (RNF-06).
    """
    db = get_db()
    cambiado = db.execute(
        "UPDATE inventarios_biologicos SET cantidad_disponible = cantidad_disponible + ?"
        " WHERE id = ? AND cantidad_disponible + ? >= 0",
        (cantidad, inventario_id, cantidad),
    ).rowcount
    if not cambiado:
        raise ErroresFormulario({"cantidad": "El saldo no puede quedar negativo."})
    db.execute(
        "INSERT INTO movimientos_inventario (inventario_id, cantidad, tipo, motivo,"
        " usuario_id, fecha, clave) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (inventario_id, cantidad, tipo, motivo, usuario_id, ahora().isoformat(), clave),
    )


def mover_lote(punto_id, lote_id, cantidad, tipo, motivo, usuario_id):
    """mover_saldo() buscando el inventario por punto y lote. No hace commit."""
    fila = get_db().execute(
        "SELECT id FROM inventarios_biologicos WHERE punto_id = ? AND lote_id = ?",
        (punto_id, lote_id),
    ).fetchone()
    if fila is None:
        raise ValueError("Ese lote no tiene existencias registradas en este punto.")
    mover_saldo(fila["id"], cantidad, tipo, motivo, usuario_id)


class Inventario:
    def __init__(self, id=None, punto_id=None, lote_id=None, cantidad_disponible=0):
        self.id = id
        self.punto_id = punto_id
        self.lote_id = lote_id
        self.cantidad_disponible = cantidad_disponible

    def mover(self, cantidad, tipo, motivo, usuario_id, clave=None):
        """Cambia el saldo y guarda el movimiento en una sola transacción."""
        db = get_db()
        try:
            with db:
                mover_saldo(self.id, cantidad, tipo, motivo, usuario_id, clave)
        except sqlite3.IntegrityError:
            if clave and db.execute(
                "SELECT 1 FROM movimientos_inventario WHERE clave = ?", (clave,)
            ).fetchone():
                return  # el mismo formulario ya se había registrado
            raise
        self.cantidad_disponible += cantidad

    def ajustar(self, cantidad, motivo, usuario_id, clave=None):
        """Aumenta o disminuye el saldo con motivo (RF-24). Bajas de vencidos incluidas."""
        errores = {}
        try:
            cantidad = entero_requerido(cantidad)
            if cantidad == 0:
                raise ValueError
        except ValueError:
            errores["cantidad"] = "Escribe un número distinto de 0 (negativo para disminuir)."
        motivo = validar_motivo(motivo, errores)
        if errores:
            raise ErroresFormulario(errores)
        self.mover(cantidad, "ajuste", motivo, usuario_id, clave)

    @staticmethod
    def buscar(inventario_id):
        fila = get_db().execute(
            "SELECT * FROM inventarios_biologicos WHERE id = ?", (inventario_id,)
        ).fetchone()
        return Inventario(**dict(fila)) if fila else None

    @staticmethod
    def detalle(inventario_id):
        """Datos del inventario con punto, vacuna y lote, para mostrar."""
        return get_db().execute(
            "SELECT i.*, p.nombre AS punto, v.nombre AS vacuna, l.codigo AS lote,"
            " l.fecha_vencimiento FROM inventarios_biologicos i"
            " JOIN puntos_vacunacion p ON p.id = i.punto_id"
            " JOIN lotes l ON l.id = i.lote_id JOIN vacunas v ON v.id = l.vacuna_id"
            " WHERE i.id = ?",
            (inventario_id,),
        ).fetchone()

    @staticmethod
    def listar(puntos_ids=None):
        """Saldo físico por punto, vacuna y lote. puntos_ids limita a esos puntos."""
        consulta = (
            "SELECT i.id, i.cantidad_disponible, p.nombre AS punto, v.nombre AS vacuna,"
            " l.codigo AS lote, l.fecha_vencimiento, l.fecha_vencimiento < ? AS vencido"
            " FROM inventarios_biologicos i"
            " JOIN puntos_vacunacion p ON p.id = i.punto_id"
            " JOIN lotes l ON l.id = i.lote_id JOIN vacunas v ON v.id = l.vacuna_id"
        )
        parametros = [hoy()]
        if puntos_ids is not None:
            consulta += " WHERE i.punto_id IN (%s)" % ",".join("?" for _ in puntos_ids or [0])
            parametros += list(puntos_ids) or [0]
        consulta += " ORDER BY p.nombre, v.nombre, l.fecha_vencimiento"
        return get_db().execute(consulta, parametros).fetchall()

    @staticmethod
    def resumen(puntos_ids=None):
        """Por punto y vacuna: dosis utilizables, reservadas y faltante (RF-26)."""
        db = get_db()
        consulta = (
            "SELECT DISTINCT i.punto_id, l.vacuna_id, p.nombre AS punto, v.nombre AS vacuna"
            " FROM inventarios_biologicos i JOIN lotes l ON l.id = i.lote_id"
            " JOIN puntos_vacunacion p ON p.id = i.punto_id JOIN vacunas v ON v.id = l.vacuna_id"
            " ORDER BY p.nombre, v.nombre"
        )
        filas = []
        for fila in db.execute(consulta):
            if puntos_ids is not None and fila["punto_id"] not in puntos_ids:
                continue
            utilizables = sum(cantidad for _, cantidad in lotes_utilizables(
                fila["punto_id"], fila["vacuna_id"]))
            reservadas = len(fechas_reservadas(fila["punto_id"], fila["vacuna_id"]))
            filas.append({
                "punto": fila["punto"],
                "vacuna": fila["vacuna"],
                "utilizables": utilizables,
                "reservadas": reservadas,
                "faltante": dosis_sin_cubrir(fila["punto_id"], fila["vacuna_id"]),
            })
        return filas

    @staticmethod
    def movimientos(limite=200):
        return get_db().execute(
            "SELECT m.*, u.nombre_completo AS autor, p.nombre AS punto, v.nombre AS vacuna,"
            " l.codigo AS lote FROM movimientos_inventario m"
            " JOIN usuarios u ON u.id = m.usuario_id"
            " JOIN inventarios_biologicos i ON i.id = m.inventario_id"
            " JOIN puntos_vacunacion p ON p.id = i.punto_id"
            " JOIN lotes l ON l.id = i.lote_id JOIN vacunas v ON v.id = l.vacuna_id"
            " ORDER BY m.id DESC LIMIT ?",
            (limite,),
        ).fetchall()


# --- Disponibilidad (RF-14, RF-25, RF-26) -------------------------------------


def lotes_utilizables(punto_id, vacuna_id):
    """[(vencimiento, unidades)] de lotes con saldo y no vencidos, del que vence primero."""
    filas = get_db().execute(
        "SELECT l.fecha_vencimiento, i.cantidad_disponible FROM inventarios_biologicos i"
        " JOIN lotes l ON l.id = i.lote_id"
        " WHERE i.punto_id = ? AND l.vacuna_id = ? AND i.cantidad_disponible > 0"
        " AND l.fecha_vencimiento >= ? ORDER BY l.fecha_vencimiento",
        (punto_id, vacuna_id, hoy()),
    ).fetchall()
    return [(fila[0], fila[1]) for fila in filas]


def fechas_reservadas(punto_id, vacuna_id, excluir_cita_id=None):
    """Fechas de las citas que apartan una dosis de esa vacuna en ese punto."""
    filas = get_db().execute(
        "SELECT f.fecha FROM citas c JOIN franjas f ON f.id = c.franja_id"
        " WHERE f.punto_id = ? AND c.vacuna_id = ? AND c.estado IN (?, ?) AND c.id != ?",
        (punto_id, vacuna_id, *ESTADOS_QUE_RESERVAN, excluir_cita_id or 0),
    ).fetchall()
    return [fila[0] for fila in filas]


def dosis_sin_cubrir(punto_id, vacuna_id, fechas_nuevas=(), excluir_cita_id=None):
    """Cuántas reservas se quedan sin una dosis utilizable.

    Recorre las reservas de la más próxima a la más lejana y a cada una le
    aparta, solo en memoria, una unidad del lote que vence primero y todavía
    sirve en su fecha. Así las unidades que duran más quedan para las citas
    más lejanas. No se guarda ningún lote en la cita.
    """
    lotes = [[vence, unidades] for vence, unidades in lotes_utilizables(punto_id, vacuna_id)]
    fechas = fechas_reservadas(punto_id, vacuna_id, excluir_cita_id) + list(fechas_nuevas)
    sin_cubrir = 0
    for fecha in sorted(max(fecha, hoy()) for fecha in fechas):
        lote = next((lote for lote in lotes if lote[1] > 0 and lote[0] >= fecha), None)
        if lote is None:
            sin_cubrir += 1
        else:
            lote[1] -= 1
    return sin_cubrir


def hay_dosis(punto_id, vacuna_id, fecha, excluir_cita_id=None):
    """True si se puede reservar una dosis más para esa fecha.

    Si ya hay un faltante, la respuesta es False: una reserva nueva no puede
    ocultarlo (RF-26).
    """
    return dosis_sin_cubrir(punto_id, vacuna_id, [fecha], excluir_cita_id) == 0
