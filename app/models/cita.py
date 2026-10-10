"""Modelo de citas: reserva, cancelación, reprogramación, llegada y cierre.

Estados (RF-41): reservada y presente ocupan cupo y apartan una dosis;
aplicada, no aplicada y registro anulado siguen ocupando cupo; cancelada y
no asistió lo liberan. Las reglas se revisan dentro de una transacción
exclusiva para que dos solicitudes no tomen el mismo cupo o dosis (RNF-06).
"""

import sqlite3
from datetime import datetime, timedelta

from app.db import get_db, transaccion_exclusiva
from app.models.auditoria import registrar_auditoria
from app.models.campana import Campana
from app.models.franja import ESTADOS_QUE_OCUPAN, Franja
from app.models.inventario import hay_dosis
from app.models.notificacion import avisar
from app.models.punto import Punto
from app.utils import ZONA_HORARIA, ErroresFormulario, ahora

ESTADOS_ACTIVOS = ("reservada", "presente")
PLAZO_PACIENTE = timedelta(hours=2)
TOLERANCIA_LLEGADA = timedelta(minutes=30)
NOMBRES_ESTADO = {
    "reservada": "Reservada", "presente": "Presente", "aplicada": "Aplicada",
    "no_aplicada": "No aplicada", "registro_anulado": "Registro anulado",
    "cancelada": "Cancelada", "no_asistio": "No asistió",
}
MARCAS_OCUPAN = ", ".join("?" for _ in ESTADOS_QUE_OCUPAN)


def fecha_hora(fecha, hora):
    """'YYYY-MM-DD' y 'HH:MM' a fecha y hora de Colombia."""
    return datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONA_HORARIA)


def numero(valor, mensaje):
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValueError(mensaje)


def motivo_requerido(motivo):
    motivo = (motivo or "").strip()
    if not motivo or len(motivo) > 1000:
        raise ErroresFormulario({"motivo": "Escribe el motivo (máximo 1000 caracteres)."})
    return motivo


def paciente_de(usuario):
    """Id del paciente de una cuenta de paciente; PermissionError para el personal."""
    fila = get_db().execute(
        "SELECT id FROM pacientes WHERE usuario_id = ?", (usuario.id,)
    ).fetchone()
    if usuario.rol != "paciente" or fila is None:
        raise PermissionError("Solo un paciente puede reservar para sí mismo.")
    return fila["id"]


def revisar_destino(paciente_id, campana_id, vacuna_id, franja_id, por_paciente, excluir_cita_id=None):
    """Comprueba que se pueda reservar (o reprogramar hacia) esa campaña, vacuna y franja.

    Devuelve (campana_id, vacuna_id, franja_id) como enteros o lanza ValueError
    con el motivo. excluir_cita_id es la propia cita al reprogramar: su cupo y
    su dosis no cuentan dos veces.
    """
    db = get_db()
    campana_id = numero(campana_id, "Elige una campaña.")
    vacuna_id = numero(vacuna_id, "Elige una vacuna.")
    franja_id = numero(franja_id, "Elige una franja.")
    excluir = excluir_cita_id or 0

    campana = Campana.buscar(campana_id)
    if campana is None or campana.estado != "publicada":
        raise ValueError("Esa campaña no está recibiendo reservas.")
    if vacuna_id not in campana.vacunas_ids:
        raise ValueError("Esa vacuna no hace parte de la campaña.")
    franja = Franja.buscar(franja_id)
    if (franja is None or franja.punto_id not in campana.puntos_ids
            or not campana.fecha_inicio <= franja.fecha <= campana.fecha_fin):
        raise ValueError("Esa franja no hace parte de la campaña.")

    inicio = fecha_hora(franja.fecha, franja.hora_inicio)
    if por_paciente and ahora() > inicio - PLAZO_PACIENTE:
        raise ValueError("Solo puedes reservar hasta 2 horas antes del inicio de la franja.")
    if not por_paciente and inicio <= ahora():
        raise ValueError("La franja de destino ya comenzó.")

    # Una cita activa por vacuna y sin superar el esquema (RF-16).
    if db.execute(
        "SELECT 1 FROM citas WHERE paciente_id = ? AND vacuna_id = ? AND id != ?"
        " AND estado IN ('reservada', 'presente')",
        (paciente_id, vacuna_id, excluir),
    ).fetchone():
        raise ValueError("Ya hay una cita activa para esta vacuna.")
    aplicadas = db.execute(  # En M09 solo contarán las aplicaciones vigentes.
        "SELECT COUNT(*) FROM dosis_aplicadas WHERE paciente_id = ? AND vacuna_id = ?",
        (paciente_id, vacuna_id),
    ).fetchone()[0]
    requeridas = db.execute("SELECT dosis_requeridas FROM vacunas WHERE id = ?", (vacuna_id,)).fetchone()[0]
    if aplicadas >= requeridas:
        raise ValueError("Ya están registradas todas las dosis de esta vacuna.")

    # Cupos de la franja, compartidos entre campañas, y capacidad diaria (RF-11).
    ocupados = db.execute(
        f"SELECT COUNT(*) FROM citas WHERE franja_id = ? AND id != ? AND estado IN ({MARCAS_OCUPAN})",
        (franja_id, excluir, *ESTADOS_QUE_OCUPAN),
    ).fetchone()[0]
    if ocupados >= franja.cupos:
        raise ValueError("No quedan cupos en esa franja.")
    del_dia = db.execute(
        "SELECT COUNT(*) FROM citas c JOIN franjas f ON f.id = c.franja_id"
        f" WHERE f.punto_id = ? AND f.fecha = ? AND c.id != ? AND c.estado IN ({MARCAS_OCUPAN})",
        (franja.punto_id, franja.fecha, excluir, *ESTADOS_QUE_OCUPAN),
    ).fetchone()[0]
    if del_dia >= Punto.buscar(franja.punto_id).capacidad_diaria:
        raise ValueError("El punto ya completó su capacidad de ese día.")

    # Una dosis utilizable para esa fecha, sin ocultar un faltante (RF-14, 25, 26).
    if not hay_dosis(franja.punto_id, vacuna_id, franja.fecha, excluir_cita_id):
        raise ValueError("No hay dosis disponibles de esa vacuna en ese punto para esa fecha.")
    return campana_id, vacuna_id, franja_id


def preparar():
    """Antes de consultar u operar: cierra inasistencias y campañas vencidas (RF-09, RF-20)."""
    Cita.procesar_vencidas()
    Campana.finalizar_vencidas()


class Cita:
    def __init__(
        self,
        id=None,
        paciente_id=None,
        campana_id=None,
        vacuna_id=None,
        franja_id=None,
        estado="reservada",
        creado_en=None,
        llegada_en=None,
        llegada_por=None,
        cierre_en=None,
        motivo=None,
        punto_id=None,
        fecha=None,
        hora_inicio=None,
        hora_fin=None,
        paciente_usuario_id=None,
        paciente=None,
        documento=None,
        campana=None,
        vacuna=None,
        punto=None,
    ):
        self.id = id
        self.paciente_id = paciente_id
        self.campana_id = campana_id
        self.vacuna_id = vacuna_id
        self.franja_id = franja_id
        self.estado = estado
        self.creado_en = creado_en
        self.llegada_en = llegada_en
        self.llegada_por = llegada_por
        self.cierre_en = cierre_en
        self.motivo = motivo
        # Datos de la franja y nombres para mostrar (vienen de buscar/listar).
        self.punto_id = punto_id
        self.fecha = fecha
        self.hora_inicio = hora_inicio
        self.hora_fin = hora_fin
        self.paciente_usuario_id = paciente_usuario_id
        self.paciente = paciente
        self.documento = documento
        self.campana = campana
        self.vacuna = vacuna
        self.punto = punto

    # --- Consultas sobre una cita --------------------------------------------

    def inicio(self):
        return fecha_hora(self.fecha, self.hora_inicio)

    def fin(self):
        return fecha_hora(self.fecha, self.hora_fin)

    def nombre_estado(self):
        return NOMBRES_ESTADO[self.estado]

    def es_de(self, usuario):
        return usuario.rol == "paciente" and self.paciente_usuario_id == usuario.id

    def puede_operar(self, usuario):
        """Personal autorizado: administrador o vacunador asignado al punto."""
        if usuario.rol == "administrador":
            return True
        return usuario.rol == "vacunador" and usuario.tiene_punto(self.punto_id)

    def paciente_puede_cambiar(self):
        """El paciente cancela o reprograma una cita reservada hasta 2 horas antes (RF-15)."""
        return self.estado == "reservada" and ahora() <= self.inicio() - PLAZO_PACIENTE

    def llegada_abierta(self):
        """Ventana de llegada: desde el inicio hasta 30 minutos después del fin (RF-19)."""
        return self.estado == "reservada" and self.inicio() <= ahora() < self.fin() + TOLERANCIA_LLEGADA

    # --- Operaciones ----------------------------------------------------------

    @staticmethod
    def reservar(usuario, campana_id, vacuna_id, franja_id):
        """El paciente reserva una cita (RF-14). Devuelve el id de la cita."""
        paciente_id = paciente_de(usuario)
        preparar()
        try:
            with transaccion_exclusiva() as db:
                campana_id, vacuna_id, franja_id = revisar_destino(
                    paciente_id, campana_id, vacuna_id, franja_id, por_paciente=True)
                cursor = db.execute(
                    "INSERT INTO citas (paciente_id, campana_id, vacuna_id, franja_id, estado, creado_en)"
                    " VALUES (?, ?, ?, ?, 'reservada', ?)",
                    (paciente_id, campana_id, vacuna_id, franja_id, ahora().isoformat()),
                )
        except sqlite3.IntegrityError:
            # Respaldo del índice único: otra reserva activa de la misma vacuna.
            raise ValueError("Ya hay una cita activa para esta vacuna.")
        return cursor.lastrowid

    def cancelar(self, usuario, motivo=None):
        """Cancela la cita (RF-17 paciente, RF-21 personal) y libera cupo y dosis."""
        preparar()
        aviso = None
        with transaccion_exclusiva():
            actual = Cita.buscar(self.id)  # datos actuales dentro de la transacción
            if usuario.rol == "paciente":
                if not actual.es_de(usuario):
                    raise PermissionError("Esta cita no es tuya.")
                if not actual.paciente_puede_cambiar():
                    raise ValueError("Solo puedes cancelar una cita reservada hasta 2 horas antes.")
                motivo = "Cancelada por el paciente."
            else:
                if not actual.puede_operar(usuario):
                    raise PermissionError("No atiendes en el punto de esta cita.")
                if actual.estado not in ESTADOS_ACTIVOS:
                    raise ValueError("Solo se cancelan citas reservadas o con llegada registrada.")
                motivo = motivo_requerido(motivo)
                aviso = avisar(actual.paciente_usuario_id, "Cita cancelada",
                               f"Tu cita de {actual.vacuna} del {actual.fecha} a las "
                               f"{actual.hora_inicio} en {actual.punto} fue cancelada. Motivo: {motivo}",
                               actual.id)
            actual.cerrar("cancelada", motivo)
            registrar_auditoria(usuario.id, "cita_cancelada", "citas", actual.id,
                                {"antes": actual.estado}, motivo)
        if aviso:
            aviso.enviar()  # el correo va después del commit

    def reprogramar(self, usuario, campana_id, vacuna_id, franja_id, motivo=None):
        """Mueve la cita a otra campaña, vacuna o franja (RF-18 paciente, RF-22 personal).

        Si algo falla, la cita original queda igual.
        """
        preparar()
        aviso = None
        with transaccion_exclusiva() as db:
            actual = Cita.buscar(self.id)
            por_paciente = usuario.rol == "paciente"
            if por_paciente and not actual.es_de(usuario):
                raise PermissionError("Esta cita no es tuya.")
            if not por_paciente and not actual.puede_operar(usuario):
                raise PermissionError("No atiendes en el punto de esta cita.")
            if actual.estado != "reservada":
                raise ValueError("Solo se reprograma una cita reservada, sin llegada ni aplicación.")
            if por_paciente and not actual.paciente_puede_cambiar():
                raise ValueError("Solo puedes reprogramar hasta 2 horas antes de tu cita.")
            if not por_paciente:
                motivo = motivo_requerido(motivo)
            campana_id, vacuna_id, franja_id = revisar_destino(
                actual.paciente_id, campana_id, vacuna_id, franja_id, por_paciente, actual.id)
            db.execute(
                "UPDATE citas SET campana_id = ?, vacuna_id = ?, franja_id = ? WHERE id = ?",
                (campana_id, vacuna_id, franja_id, actual.id),
            )
            registrar_auditoria(usuario.id, "cita_reprogramada", "citas", actual.id, {
                "antes": [actual.campana_id, actual.vacuna_id, actual.franja_id],
                "despues": [campana_id, vacuna_id, franja_id]}, motivo)
            if not por_paciente:
                nueva = Cita.buscar(actual.id)
                aviso = avisar(actual.paciente_usuario_id, "Cita reprogramada",
                               f"Tu cita pasó al {nueva.fecha} a las {nueva.hora_inicio} en "
                               f"{nueva.punto} ({nueva.vacuna}). Motivo: {motivo}", actual.id)
        if aviso:
            aviso.enviar()

    def registrar_llegada(self, usuario):
        """El personal del punto marca al paciente como presente (RF-19)."""
        preparar()
        with transaccion_exclusiva() as db:
            actual = Cita.buscar(self.id)
            if not actual.puede_operar(usuario):
                raise PermissionError("No atiendes en el punto de esta cita.")
            if not actual.llegada_abierta():
                raise ValueError("La llegada se registra desde el inicio de la franja hasta "
                                 "30 minutos después de su fin, en citas reservadas.")
            db.execute(
                "UPDATE citas SET estado = 'presente', llegada_en = ?, llegada_por = ? WHERE id = ?",
                (ahora().isoformat(), usuario.id, actual.id),
            )

    def cerrar_sin_aplicar(self, usuario, motivo):
        """El vacunador cierra la atención sin vacunar (RF-38): libera la dosis
        apartada y la cita sigue ocupando capacidad (RF-41)."""
        with transaccion_exclusiva():
            actual = Cita.buscar(self.id)
            if usuario.rol != "vacunador" or not usuario.tiene_punto(actual.punto_id):
                raise PermissionError("Solo el vacunador del punto cierra la atención.")
            if actual.estado != "presente":
                raise ValueError("Solo se cierra sin aplicar una cita con llegada registrada.")
            actual.cerrar("no_aplicada", motivo_requerido(motivo))

    def cerrar(self, estado, motivo):
        """Pasa la cita a un estado cerrado. Sin commit: lo hace quien llama."""
        get_db().execute(
            "UPDATE citas SET estado = ?, cierre_en = ?, motivo = ? WHERE id = ?",
            (estado, ahora().isoformat(), motivo, self.id),
        )

    @staticmethod
    def procesar_vencidas():
        """Marca «no asistió» las citas reservadas cuya franja terminó hace 30
        minutos o más (RF-20). Las presentes nunca se tocan. Sin tareas programadas:
        se llama al arrancar y antes de consultar u operar."""
        db = get_db()
        db.execute(
            "UPDATE citas SET estado = 'no_asistio', cierre_en = ?"
            " WHERE estado = 'reservada' AND franja_id IN ("
            "   SELECT id FROM franjas WHERE datetime(fecha || ' ' || hora_fin, '+30 minutes') <= ?)",
            (ahora().isoformat(), ahora().strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.commit()

    # --- Búsquedas ------------------------------------------------------------

    CONSULTA = (
        "SELECT c.*, f.punto_id, f.fecha, f.hora_inicio, f.hora_fin,"
        " p.usuario_id AS paciente_usuario_id, u.nombre_completo AS paciente,"
        " u.tipo_documento || ' ' || u.identificacion AS documento,"
        " ca.nombre AS campana, v.nombre AS vacuna, pu.nombre AS punto"
        " FROM citas c JOIN franjas f ON f.id = c.franja_id"
        " JOIN pacientes p ON p.id = c.paciente_id JOIN usuarios u ON u.id = p.usuario_id"
        " JOIN campanas ca ON ca.id = c.campana_id JOIN vacunas v ON v.id = c.vacuna_id"
        " JOIN puntos_vacunacion pu ON pu.id = f.punto_id"
    )

    @staticmethod
    def buscar(cita_id):
        fila = get_db().execute(Cita.CONSULTA + " WHERE c.id = ?", (cita_id,)).fetchone()
        return Cita(**dict(fila)) if fila else None

    @staticmethod
    def de_paciente(usuario_id):
        filas = get_db().execute(
            Cita.CONSULTA + " WHERE p.usuario_id = ? ORDER BY f.fecha DESC, f.hora_inicio DESC",
            (usuario_id,),
        ).fetchall()
        return [Cita(**dict(fila)) for fila in filas]

    @staticmethod
    def agenda(usuario, fecha=None, punto_id=None):
        """Citas para el personal: el vacunador solo ve sus puntos asignados (RF-31)."""
        consulta = Cita.CONSULTA + " WHERE 1 = 1"
        parametros = []
        if usuario.rol == "vacunador":
            consulta += " AND f.punto_id IN (SELECT punto_id FROM vacunador_punto WHERE usuario_id = ?)"
            parametros.append(usuario.id)
        if fecha:
            consulta += " AND f.fecha = ?"
            parametros.append(fecha)
        if punto_id:
            consulta += " AND f.punto_id = ?"
            parametros.append(punto_id)
        consulta += " ORDER BY f.fecha, f.hora_inicio, pu.nombre"
        return [Cita(**dict(fila)) for fila in get_db().execute(consulta, parametros)]

    @staticmethod
    def franjas_disponibles(campana, por_paciente=True):
        """Franjas de la campaña que todavía se pueden elegir, con sus cupos libres.

        Es una ayuda para el formulario: al guardar se revisa todo otra vez.
        """
        opciones = []
        for franja in campana.franjas():
            inicio = fecha_hora(franja["fecha"], franja["hora_inicio"])
            limite = inicio - PLAZO_PACIENTE if por_paciente else inicio
            libres = franja["cupos"] - Franja.buscar(franja["id"]).ocupados()
            if ahora() <= limite and libres > 0:
                opciones.append({
                    "id": franja["id"],
                    "nombre": f"{franja['punto']} · {franja['fecha']} · {franja['hora_inicio']}–"
                              f"{franja['hora_fin']} · {libres} cupo(s) libre(s)",
                })
        return opciones
