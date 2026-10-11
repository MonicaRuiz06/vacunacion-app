"""Modelo de dosis aplicadas: aplicar, corregir, anular y rectificar.

Cada operación cambia la aplicación, la cita y el inventario en una sola
transacción: nunca queda una aplicación sin descuento ni un descuento sin
aplicación (RF-28). Los cambios quedan en la auditoría con su motivo.
"""

import sqlite3

from app.db import get_db, transaccion_exclusiva
from app.models.auditoria import registrar_auditoria
from app.models.cita import Cita, motivo_requerido, numero
from app.models.inventario import mover_lote
from app.utils import ErroresFormulario, ahora


def numero_valido(numero_dosis, vacuna_id, paciente_id, excluir_dosis_id=None):
    """Número de dosis entre 1 y las requeridas, sin repetir una vigente (RF-29)."""
    db = get_db()
    requeridas = db.execute("SELECT dosis_requeridas FROM vacunas WHERE id = ?", (vacuna_id,)).fetchone()[0]
    try:
        numero_dosis = int(numero_dosis)
        if not 1 <= numero_dosis <= requeridas:
            raise ValueError
    except (TypeError, ValueError):
        raise ErroresFormulario({"numero_dosis": f"El número de dosis va de 1 a {requeridas}."})
    if db.execute(
        "SELECT 1 FROM dosis_aplicadas WHERE paciente_id = ? AND vacuna_id = ? AND numero_dosis = ?"
        " AND estado = 'vigente' AND id != ?",
        (paciente_id, vacuna_id, numero_dosis, excluir_dosis_id or 0),
    ).fetchone():
        raise ErroresFormulario({"numero_dosis": f"La dosis {numero_dosis} ya está registrada."})
    return numero_dosis


def lote_valido(lote_id, vacuna_id, punto_id, fecha, requiere_saldo=True):
    """El lote es de esa vacuna, sirve en esa fecha y tiene existencias en el punto (RF-25, RF-27)."""
    lote_id = numero(lote_id, "Elige un lote.")
    fila = get_db().execute(
        "SELECT l.vacuna_id, l.fecha_vencimiento, i.cantidad_disponible FROM lotes l"
        " LEFT JOIN inventarios_biologicos i ON i.lote_id = l.id AND i.punto_id = ?"
        " WHERE l.id = ?",
        (punto_id, lote_id),
    ).fetchone()
    if fila is None or fila["vacuna_id"] != vacuna_id:
        raise ValueError("Ese lote no es de la vacuna de la cita.")
    if fila["fecha_vencimiento"] < fecha:
        raise ValueError("Ese lote estaba vencido en la fecha de aplicación.")
    if fila["cantidad_disponible"] is None or (requiere_saldo and not fila["cantidad_disponible"]):
        raise ValueError("Ese lote no tiene existencias en este punto.")
    return lote_id


def cita_para_aplicar(cita_id):
    """Cita con llegada registrada y sin aplicación vigente."""
    cita = Cita.buscar(cita_id)
    if cita is None or cita.estado != "presente":
        raise ValueError("Solo se aplica en una cita con llegada registrada y sin aplicación.")
    return cita


class DosisAplicada:
    def __init__(
        self,
        id=None,
        cita_id=None,
        paciente_id=None,
        vacuna_id=None,
        punto_id=None,
        lote_id=None,
        numero_dosis=1,
        fecha_aplicacion=None,
        registrado_en=None,
        registrado_por=None,
        estado="vigente",
        rectifica_id=None,
        paciente=None,
        vacuna=None,
        punto=None,
        lote=None,
        autor=None,
    ):
        self.id = id
        self.cita_id = cita_id
        self.paciente_id = paciente_id
        self.vacuna_id = vacuna_id
        self.punto_id = punto_id
        self.lote_id = lote_id
        self.numero_dosis = numero_dosis
        self.fecha_aplicacion = fecha_aplicacion
        self.registrado_en = registrado_en
        self.registrado_por = registrado_por
        self.estado = estado
        self.rectifica_id = rectifica_id
        # Nombres para mostrar (vienen de buscar/listar).
        self.paciente = paciente
        self.vacuna = vacuna
        self.punto = punto
        self.lote = lote
        self.autor = autor

    @staticmethod
    def insertar(cita, lote_id, numero_dosis, fecha, usuario_id, rectifica_id=None):
        """Crea la aplicación, descuenta una unidad y cierra la cita. Sin commit."""
        db = get_db()
        cursor = db.execute(
            "INSERT INTO dosis_aplicadas (cita_id, paciente_id, vacuna_id, punto_id, lote_id,"
            " numero_dosis, fecha_aplicacion, registrado_en, registrado_por, rectifica_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cita.id, cita.paciente_id, cita.vacuna_id, cita.punto_id, lote_id, numero_dosis,
             fecha, ahora().isoformat(), usuario_id, rectifica_id),
        )
        cita.cerrar("aplicada", None)
        return cursor.lastrowid

    @staticmethod
    def registrar(cita_id, usuario, lote_id, numero_dosis):
        """El vacunador del punto registra la aplicación (RF-27, RF-28, RF-29).

        Confirmar dos veces no duplica: la segunda vez la cita ya no está presente.
        """
        try:
            with transaccion_exclusiva():
                cita = cita_para_aplicar(cita_id)
                if usuario.rol != "vacunador" or not usuario.tiene_punto(cita.punto_id):
                    raise PermissionError("Solo el vacunador del punto registra la aplicación.")
                hoy = ahora().date().isoformat()
                lote_id = lote_valido(lote_id, cita.vacuna_id, cita.punto_id, hoy)
                numero_dosis = numero_valido(numero_dosis, cita.vacuna_id, cita.paciente_id)
                dosis_id = DosisAplicada.insertar(cita, lote_id, numero_dosis, hoy, usuario.id)
                mover_lote(cita.punto_id, lote_id, -1, "aplicacion", f"Aplicación de la cita {cita.id}",
                           usuario.id)
        except sqlite3.IntegrityError:
            raise ValueError("Esta cita ya tiene una aplicación registrada.")
        return dosis_id

    def puede_corregir(self, usuario):
        """El administrador, o el vacunador autor mientras siga asignado al punto (RF-30)."""
        if usuario.rol == "administrador":
            return True
        return (usuario.rol == "vacunador" and usuario.id == self.registrado_por
                and usuario.tiene_punto(self.punto_id))

    def corregir(self, usuario, motivo, lote_id=None, numero_dosis=None):
        """Corrige solo el lote o el número de dosis, con motivo (RF-30).

        Si cambia el lote se repone una unidad al anterior y se descuenta del
        nuevo, que debía servir en la fecha real de aplicación.
        """
        with transaccion_exclusiva() as db:
            actual = DosisAplicada.buscar(self.id)
            if not actual.puede_corregir(usuario):
                raise PermissionError("Solo el administrador o el autor asignado al punto corrige.")
            if actual.estado != "vigente":
                raise ValueError("Solo se corrige una aplicación vigente.")
            motivo = motivo_requerido(motivo)
            nuevo_lote = actual.lote_id if lote_id in (None, "") else lote_valido(
                lote_id, actual.vacuna_id, actual.punto_id, actual.fecha_aplicacion)
            nuevo_numero = actual.numero_dosis if numero_dosis in (None, "") else numero_valido(
                numero_dosis, actual.vacuna_id, actual.paciente_id, actual.id)
            if (nuevo_lote, nuevo_numero) == (actual.lote_id, actual.numero_dosis):
                raise ValueError("No hay cambios para corregir.")
            if nuevo_lote != actual.lote_id:
                texto = f"Corrección de la aplicación {actual.id}"
                mover_lote(actual.punto_id, actual.lote_id, 1, "correccion", texto, usuario.id)
                mover_lote(actual.punto_id, nuevo_lote, -1, "correccion", texto, usuario.id)
            db.execute("UPDATE dosis_aplicadas SET lote_id = ?, numero_dosis = ? WHERE id = ?",
                       (nuevo_lote, nuevo_numero, actual.id))
            registrar_auditoria(usuario.id, "dosis_corregida", "dosis_aplicadas", actual.id, {
                "antes": {"lote_id": actual.lote_id, "numero_dosis": actual.numero_dosis},
                "despues": {"lote_id": nuevo_lote, "numero_dosis": nuevo_numero}}, motivo)

    def anular(self, usuario, motivo, dosis_usada):
        """El administrador anula una aplicación registrada por error (RF-39).

        La cita queda como «registro anulado» y sigue ocupando capacidad. Solo
        si la dosis no se usó se repone una unidad; anular de nuevo no repone.
        """
        if usuario.rol != "administrador":
            raise PermissionError("Solo el administrador anula aplicaciones.")
        with transaccion_exclusiva() as db:
            actual = DosisAplicada.buscar(self.id)
            if actual.estado != "vigente":
                raise ValueError("Esta aplicación ya está anulada.")
            motivo = motivo_requerido(motivo)
            db.execute("UPDATE dosis_aplicadas SET estado = 'anulada' WHERE id = ?", (actual.id,))
            Cita.buscar(actual.cita_id).cerrar("registro_anulado", motivo)
            if not dosis_usada:
                mover_lote(actual.punto_id, actual.lote_id, 1, "anulacion",
                           f"Anulación de la aplicación {actual.id}: dosis no usada", usuario.id)
            registrar_auditoria(usuario.id, "dosis_anulada", "dosis_aplicadas", actual.id,
                                {"dosis_usada": bool(dosis_usada)}, motivo)

    def rectificar(self, usuario, cita_destino_id, lote_id, numero_dosis, motivo):
        """Rectificación excepcional de paciente o vacuna (RF-42).

        Anula este registro y crea el correcto en una cita existente con llegada
        y sin aplicación, del mismo punto y fecha. Conserva la fecha real y
        concilia el inventario sin doble descuento. Devuelve el id nuevo.
        """
        if usuario.rol != "administrador":
            raise PermissionError("Solo el administrador rectifica aplicaciones.")
        with transaccion_exclusiva() as db:
            actual = DosisAplicada.buscar(self.id)
            if actual.estado != "vigente":
                raise ValueError("Solo se rectifica una aplicación vigente.")
            motivo = motivo_requerido(motivo)
            destino = cita_para_aplicar(numero(cita_destino_id, "Elige la cita correcta."))
            if destino.id == actual.cita_id or destino.punto_id != actual.punto_id \
                    or destino.fecha != actual.fecha_aplicacion:
                raise ValueError("La cita correcta debe ser de otra atención del mismo punto y fecha.")
            lote_id = numero(lote_id, "Elige un lote.")
            lote_id = lote_valido(lote_id, destino.vacuna_id, destino.punto_id,
                                  actual.fecha_aplicacion, requiere_saldo=lote_id != actual.lote_id)
            numero_dosis = numero_valido(numero_dosis, destino.vacuna_id, destino.paciente_id)

            db.execute("UPDATE dosis_aplicadas SET estado = 'anulada' WHERE id = ?", (actual.id,))
            Cita.buscar(actual.cita_id).cerrar("registro_anulado", motivo)
            nueva_id = DosisAplicada.insertar(destino, lote_id, numero_dosis, actual.fecha_aplicacion,
                                              usuario.id, rectifica_id=actual.id)
            # La unidad ya se descontó al registrar el original: solo se mueve si cambia el lote.
            if lote_id != actual.lote_id:
                texto = f"Rectificación de la aplicación {actual.id}"
                mover_lote(actual.punto_id, actual.lote_id, 1, "correccion", texto, usuario.id)
                mover_lote(actual.punto_id, lote_id, -1, "correccion", texto, usuario.id)
            registrar_auditoria(usuario.id, "dosis_rectificada", "dosis_aplicadas", actual.id,
                                {"reemplazada_por": nueva_id, "cita_destino": destino.id}, motivo)
        return nueva_id

    # --- Búsquedas ------------------------------------------------------------

    CONSULTA = (
        "SELECT d.*, u.nombre_completo AS paciente, v.nombre AS vacuna, p.nombre AS punto,"
        " l.codigo AS lote, a.nombre_completo AS autor FROM dosis_aplicadas d"
        " JOIN pacientes pa ON pa.id = d.paciente_id JOIN usuarios u ON u.id = pa.usuario_id"
        " JOIN vacunas v ON v.id = d.vacuna_id JOIN puntos_vacunacion p ON p.id = d.punto_id"
        " JOIN lotes l ON l.id = d.lote_id JOIN usuarios a ON a.id = d.registrado_por"
    )

    @staticmethod
    def buscar(dosis_id):
        fila = get_db().execute(DosisAplicada.CONSULTA + " WHERE d.id = ?", (dosis_id,)).fetchone()
        return DosisAplicada(**dict(fila)) if fila else None

    @staticmethod
    def listar(usuario, limite=200):
        """Aplicaciones recientes: el vacunador ve las de sus puntos asignados."""
        consulta = DosisAplicada.CONSULTA
        parametros = []
        if usuario.rol == "vacunador":
            consulta += " WHERE d.punto_id IN (SELECT punto_id FROM vacunador_punto WHERE usuario_id = ?)"
            parametros.append(usuario.id)
        consulta += " ORDER BY d.id DESC LIMIT ?"
        parametros.append(limite)
        return [DosisAplicada(**dict(fila)) for fila in get_db().execute(consulta, parametros)]

    @staticmethod
    def lotes_para(punto_id, vacuna_id, fecha):
        """Lotes que sirven en esa fecha y tienen existencias en el punto, para el formulario."""
        return get_db().execute(
            "SELECT l.id, l.codigo || ' · vence ' || l.fecha_vencimiento || ' · '"
            " || i.cantidad_disponible || ' disponibles' AS nombre"
            " FROM lotes l JOIN inventarios_biologicos i ON i.lote_id = l.id"
            " WHERE i.punto_id = ? AND l.vacuna_id = ? AND l.fecha_vencimiento >= ?"
            " AND i.cantidad_disponible > 0 ORDER BY l.fecha_vencimiento",
            (punto_id, vacuna_id, fecha),
        ).fetchall()

    @staticmethod
    def lotes_del_punto(punto_id, fecha, lote_actual_id=None):
        """Lotes utilizables y el ya consumido, aunque este haya quedado sin saldo."""
        return get_db().execute(
            "SELECT l.id, v.nombre || ' · ' || l.codigo || ' · vence ' || l.fecha_vencimiento AS nombre"
            " FROM lotes l JOIN vacunas v ON v.id = l.vacuna_id"
            " JOIN inventarios_biologicos i ON i.lote_id = l.id"
            " WHERE i.punto_id = ? AND l.fecha_vencimiento >= ? AND (i.cantidad_disponible > 0 OR l.id = ?)"
            " ORDER BY v.nombre, l.fecha_vencimiento",
            (punto_id, fecha, lote_actual_id),
        ).fetchall()

    @staticmethod
    def siguiente_numero(paciente_id, vacuna_id):
        """Sugerencia para el formulario: una más que las dosis vigentes registradas."""
        return get_db().execute(
            "SELECT COUNT(*) + 1 FROM dosis_aplicadas WHERE paciente_id = ? AND vacuna_id = ?"
            " AND estado = 'vigente'", (paciente_id, vacuna_id)).fetchone()[0]

    @staticmethod
    def citas_para_rectificar(dosis):
        """Opciones de destino: citas con llegada y sin aplicación del mismo punto y fecha."""
        filas = get_db().execute(
            Cita.CONSULTA + " WHERE f.punto_id = ? AND f.fecha = ? AND c.estado = 'presente'"
            " ORDER BY f.hora_inicio, u.nombre_completo",
            (dosis.punto_id, dosis.fecha_aplicacion),
        ).fetchall()
        return [{"id": fila["id"], "nombre": f"{fila['paciente']} · {fila['vacuna']} · {fila['hora_inicio']}"}
                for fila in filas]
