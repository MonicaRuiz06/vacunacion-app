"""Modelo de avisos: aviso interno en la cuenta y su correo (RF-36, RF-37).

Uso en una operación que cancela o reprograma una cita:

    with db:                                  # misma transacción del cambio
        ...cambiar la cita...
        aviso = avisar(usuario_id, asunto, mensaje, cita_id)
    aviso.enviar()                            # el correo va después del commit

Si el correo falla, el cambio y el aviso se conservan y el personal puede
reintentar el envío.
"""

from app.db import get_db
from app.utils import ahora, enviar_correo


def avisar(usuario_id, asunto, mensaje, cita_id=None):
    """Guarda un aviso pendiente de correo. No hace commit: lo hace quien llama."""
    aviso = Notificacion(usuario_id=usuario_id, cita_id=cita_id, asunto=asunto, mensaje=mensaje,
                         creado_en=ahora().isoformat())
    cursor = get_db().execute(
        "INSERT INTO notificaciones (usuario_id, cita_id, asunto, mensaje, creado_en)"
        " VALUES (?, ?, ?, ?, ?)",
        (usuario_id, cita_id, asunto, mensaje, aviso.creado_en),
    )
    aviso.id = cursor.lastrowid
    return aviso


class Notificacion:
    def __init__(
        self,
        id=None,
        usuario_id=None,
        cita_id=None,
        asunto="",
        mensaje="",
        creado_en=None,
        leido_en=None,
        correo_estado="pendiente",
        correo_intentos=0,
    ):
        self.id = id
        self.usuario_id = usuario_id
        self.cita_id = cita_id
        self.asunto = asunto
        self.mensaje = mensaje
        self.creado_en = creado_en
        self.leido_en = leido_en
        self.correo_estado = correo_estado
        self.correo_intentos = correo_intentos

    def enviar(self):
        """Intenta el correo una vez y guarda el resultado."""
        db = get_db()
        correo = db.execute("SELECT correo FROM usuarios WHERE id = ?", (self.usuario_id,)).fetchone()[0]
        self.correo_estado = "enviado" if enviar_correo(correo, self.asunto, self.mensaje) else "fallido"
        self.correo_intentos += 1
        db.execute(
            "UPDATE notificaciones SET correo_estado = ?, correo_intentos = ? WHERE id = ?",
            (self.correo_estado, self.correo_intentos, self.id),
        )
        db.commit()

    def puede_reintentar(self, usuario):
        """El administrador reintenta cualquier aviso; el vacunador, solo los de
        citas de sus puntos asignados en este momento (RF-37)."""
        if usuario.rol == "administrador":
            return True
        if usuario.rol != "vacunador" or self.cita_id is None:
            return False
        punto = get_db().execute(
            "SELECT f.punto_id FROM citas c JOIN franjas f ON f.id = c.franja_id WHERE c.id = ?",
            (self.cita_id,),
        ).fetchone()
        return punto is not None and usuario.tiene_punto(punto[0])

    def reintentar(self, usuario):
        """Reintento manual de un correo fallido. No repite la operación de negocio."""
        if not self.puede_reintentar(usuario):
            raise PermissionError("No puedes reintentar este aviso.")
        if self.correo_estado != "fallido":
            raise ValueError("Solo se reintentan correos fallidos.")
        self.enviar()

    @staticmethod
    def buscar(aviso_id):
        fila = get_db().execute("SELECT * FROM notificaciones WHERE id = ?", (aviso_id,)).fetchone()
        return Notificacion(**dict(fila)) if fila else None

    @staticmethod
    def de_usuario(usuario_id):
        filas = get_db().execute(
            "SELECT * FROM notificaciones WHERE usuario_id = ? ORDER BY id DESC", (usuario_id,)
        ).fetchall()
        return [Notificacion(**dict(fila)) for fila in filas]

    @staticmethod
    def marcar_leidos(usuario_id):
        db = get_db()
        db.execute(
            "UPDATE notificaciones SET leido_en = ? WHERE usuario_id = ? AND leido_en IS NULL",
            (ahora().isoformat(), usuario_id),
        )
        db.commit()

    @staticmethod
    def fallidos(usuario):
        """Correos fallidos que ese usuario puede reintentar."""
        filas = get_db().execute(
            "SELECT n.*, u.nombre_completo AS destinatario, u.correo FROM notificaciones n"
            " JOIN usuarios u ON u.id = n.usuario_id"
            " WHERE n.correo_estado = 'fallido' ORDER BY n.id DESC"
        ).fetchall()
        return [fila for fila in filas if Notificacion.buscar(fila["id"]).puede_reintentar(usuario)]
