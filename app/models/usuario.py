"""Modelo de usuarios: cuentas de administradores, vacunadores y pacientes."""

import hashlib
import re
import secrets
from datetime import timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_db
from app.models.auditoria import registrar_auditoria
from app.utils import ErroresFormulario, ahora

TIPOS_DOCUMENTO = ("CC", "CE", "PASAPORTE")
ROLES = ("administrador", "vacunador", "paciente")
MINUTOS_ENLACE = 30


def normalizar_documento(valor):
    """El documento es texto: sin espacios externos y en mayúsculas (RF-43)."""
    return (valor or "").strip().upper()


def normalizar_correo(valor):
    """Los correos se comparan sin distinguir mayúsculas (RF-43)."""
    return (valor or "").strip().lower()


def validar_contrasena(contrasena):
    """Devuelve un mensaje si la contraseña no cumple RF-05, o None si es válida."""
    contrasena = contrasena or ""
    if (
        len(contrasena) < 6
        or len(contrasena) > 128
        or not any(c.isupper() for c in contrasena)
        or not any(c.islower() for c in contrasena)
        or not any(c.isdigit() for c in contrasena)
        or all(c.isalnum() for c in contrasena)
    ):
        return "Usa al menos 6 caracteres con mayúscula, minúscula, número y símbolo."
    return None


def revisar_identidad(persona):
    """Normaliza nombre, documento y correo de un Usuario o Paciente.

    Devuelve un diccionario de errores por campo (vacío si todo está bien).
    """
    errores = {}
    persona.nombre_completo = (persona.nombre_completo or "").strip()
    persona.tipo_documento = normalizar_documento(persona.tipo_documento)
    persona.identificacion = normalizar_documento(persona.identificacion)
    persona.correo = normalizar_correo(persona.correo)

    if not persona.nombre_completo or len(persona.nombre_completo) > 200:
        errores["nombre_completo"] = "Escribe el nombre completo (máximo 200 caracteres)."
    if persona.tipo_documento not in TIPOS_DOCUMENTO:
        errores["tipo_documento"] = "Elige cédula de ciudadanía, cédula de extranjería o pasaporte."
    if not persona.identificacion or len(persona.identificacion) > 40:
        errores["identificacion"] = "Escribe el número de documento (máximo 40 caracteres)."
    if len(persona.correo) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", persona.correo):
        errores["correo"] = "Escribe un correo válido."
    return errores


def revisar_duplicados(persona, usuario_id=None):
    """Busca otra cuenta con el mismo documento o correo (RF-02)."""
    db = get_db()
    errores = {}
    otro_id = usuario_id or 0
    if db.execute(
        "SELECT 1 FROM usuarios WHERE tipo_documento = ? AND identificacion = ? AND id != ?",
        (persona.tipo_documento, persona.identificacion, otro_id),
    ).fetchone():
        errores["identificacion"] = "Este documento ya está registrado."
    if db.execute(
        "SELECT 1 FROM usuarios WHERE correo = ? AND id != ?", (persona.correo, otro_id)
    ).fetchone():
        errores["correo"] = "Este correo ya está registrado."
    return errores


def revisar_puntos(puntos_ids):
    """Convierte los puntos elegidos en ids; ValueError si alguno no existe."""
    try:
        ids = sorted({int(punto_id) for punto_id in puntos_ids})
    except (TypeError, ValueError):
        raise ValueError("Uno de los puntos elegidos no es válido.")
    db = get_db()
    for punto_id in ids:
        if not db.execute("SELECT 1 FROM puntos_vacunacion WHERE id = ?", (punto_id,)).fetchone():
            raise ValueError("Uno de los puntos elegidos no existe.")
    return ids


def listar_puntos():
    """Todos los puntos de vacunación (M04 tendrá su propio modelo de puntos)."""
    return get_db().execute("SELECT id, nombre FROM puntos_vacunacion ORDER BY nombre").fetchall()


def resumir_token(token):
    """En la base solo se guarda el hash del enlace, nunca el enlace."""
    return hashlib.sha256(token.encode()).hexdigest()


def crear_token(usuario_id, proposito):
    """Crea un enlace de un solo uso por 30 minutos y borra los anteriores.

    No hace commit: lo hace quien llama. Devuelve el token para armar el enlace.
    """
    db = get_db()
    db.execute(
        "DELETE FROM tokens_cuenta WHERE usuario_id = ? AND proposito = ?",
        (usuario_id, proposito),
    )
    token = secrets.token_urlsafe(32)
    expira = ahora() + timedelta(minutes=MINUTOS_ENLACE)
    db.execute(
        "INSERT INTO tokens_cuenta (usuario_id, proposito, token_hash, expira_en) VALUES (?, ?, ?, ?)",
        (usuario_id, proposito, resumir_token(token), expira.isoformat()),
    )
    return token


def usar_token(token, proposito, contrasena_nueva):
    """Cambia la contraseña con un enlace válido. El enlace deja de servir."""
    mensaje = validar_contrasena(contrasena_nueva)
    if mensaje:
        raise ErroresFormulario({"contrasena_nueva": mensaje})
    db = get_db()
    fila = db.execute(
        "SELECT usuario_id FROM tokens_cuenta"
        " WHERE token_hash = ? AND proposito = ? AND expira_en > ?",
        (resumir_token(token or ""), proposito, ahora().isoformat()),
    ).fetchone()
    usuario = Usuario.buscar(fila["usuario_id"]) if fila else None
    if usuario is None or not usuario.activo:
        raise ValueError("El enlace no es válido o ya venció. Solicita uno nuevo.")
    with db:
        usuario.guardar_contrasena(contrasena_nueva)
        registrar_auditoria(usuario.id, "contrasena_establecida", "usuarios", usuario.id,
                            {"medio": proposito})
    return usuario


class Usuario:
    def __init__(
        self,
        id=None,
        nombre_completo="",
        tipo_documento="CC",
        identificacion="",
        correo="",
        rol="paciente",
        activo=1,
        version_credenciales=0,
        password_hash=None,
        creado_en=None,
    ):
        self.id = id
        self.nombre_completo = nombre_completo
        self.tipo_documento = tipo_documento
        self.identificacion = identificacion
        self.correo = correo
        self.rol = rol
        self.activo = activo
        self.version_credenciales = version_credenciales
        self.password_hash = password_hash
        self.creado_en = creado_en

    def validar(self):
        errores = revisar_identidad(self)
        if self.rol not in ROLES:
            errores["rol"] = "Rol no válido."
        if errores:
            raise ErroresFormulario(errores)
        return True

    def insertar(self, contrasena=None):
        """Inserta la cuenta sin hacer commit (lo hace quien llama).

        Sin contraseña la cuenta queda pendiente de invitación.
        """
        self.password_hash = generate_password_hash(contrasena) if contrasena else None
        self.creado_en = ahora().isoformat()
        cursor = get_db().execute(
            "INSERT INTO usuarios (nombre_completo, tipo_documento, identificacion, correo,"
            " password_hash, rol, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.nombre_completo, self.tipo_documento, self.identificacion, self.correo,
             self.password_hash, self.rol, self.creado_en),
        )
        self.id = cursor.lastrowid
        return self.id

    def guardar(self, contrasena=None):
        """Valida y crea la cuenta de personal (administrador o vacunador)."""
        self.validar()
        errores = revisar_duplicados(self)
        if contrasena is not None and validar_contrasena(contrasena):
            errores["contrasena"] = validar_contrasena(contrasena)
        if errores:
            raise ErroresFormulario(errores)
        with get_db():
            return self.insertar(contrasena)

    def invitar(self, puntos_ids, actor_id):
        """Crea la cuenta de un vacunador con sus puntos (RF-06).

        Todo ocurre en una sola transacción. Devuelve el token de invitación.
        """
        self.rol = "vacunador"
        errores = {}
        try:
            self.validar()
        except ErroresFormulario as error:
            errores = error.errores
        try:
            ids = revisar_puntos(puntos_ids)
            if not ids:
                errores["puntos"] = "Elige al menos un punto."
        except ValueError as error:
            errores["puntos"] = str(error)
        if not errores:
            errores = revisar_duplicados(self)
        if errores:
            raise ErroresFormulario(errores)

        db = get_db()
        with db:
            self.insertar()  # sin contraseña: la define con el enlace
            db.executemany(
                "INSERT INTO vacunador_punto (usuario_id, punto_id) VALUES (?, ?)",
                [(self.id, punto_id) for punto_id in ids],
            )
            token = crear_token(self.id, "invitacion")
            registrar_auditoria(actor_id, "vacunador_invitado", "usuarios", self.id, {"puntos": ids})
        return token

    def comprobar_contrasena(self, contrasena):
        return bool(self.password_hash) and check_password_hash(self.password_hash, contrasena or "")

    def cerrar_sesiones(self):
        """Invalida todas las sesiones y enlaces de la cuenta (RF-44). Sin commit."""
        db = get_db()
        db.execute(
            "UPDATE usuarios SET version_credenciales = version_credenciales + 1 WHERE id = ?",
            (self.id,),
        )
        db.execute("DELETE FROM tokens_cuenta WHERE usuario_id = ?", (self.id,))
        self.version_credenciales += 1

    def guardar_contrasena(self, contrasena):
        """Guarda una contraseña nueva y cierra las sesiones. Sin commit."""
        self.password_hash = generate_password_hash(contrasena)
        get_db().execute(
            "UPDATE usuarios SET password_hash = ? WHERE id = ?", (self.password_hash, self.id)
        )
        self.cerrar_sesiones()

    def cambiar_contrasena(self, actual, nueva):
        errores = {}
        if not self.comprobar_contrasena(actual):
            errores["contrasena_actual"] = "La contraseña actual no es correcta."
        if validar_contrasena(nueva):
            errores["contrasena_nueva"] = validar_contrasena(nueva)
        if errores:
            raise ErroresFormulario(errores)
        with get_db():
            self.guardar_contrasena(nueva)
            registrar_auditoria(self.id, "contrasena_cambiada", "usuarios", self.id)

    def puntos(self):
        """Puntos de vacunación asignados (solo vacunadores)."""
        return get_db().execute(
            "SELECT p.id, p.nombre FROM puntos_vacunacion p"
            " JOIN vacunador_punto v ON v.punto_id = p.id"
            " WHERE v.usuario_id = ? ORDER BY p.nombre",
            (self.id,),
        ).fetchall()

    def tiene_punto(self, punto_id):
        return get_db().execute(
            "SELECT 1 FROM vacunador_punto WHERE usuario_id = ? AND punto_id = ?",
            (self.id, punto_id),
        ).fetchone() is not None

    def asignar_puntos(self, puntos_ids, actor_id):
        """Reemplaza los puntos del vacunador por los indicados (RF-06)."""
        db = get_db()
        ids = revisar_puntos(puntos_ids)
        antes = [punto["id"] for punto in self.puntos()]
        with db:
            db.execute("DELETE FROM vacunador_punto WHERE usuario_id = ?", (self.id,))
            db.executemany(
                "INSERT INTO vacunador_punto (usuario_id, punto_id) VALUES (?, ?)",
                [(self.id, punto_id) for punto_id in ids],
            )
            registrar_auditoria(actor_id, "puntos_asignados", "usuarios", self.id,
                                {"antes": antes, "despues": ids})

    @staticmethod
    def desde_fila(fila):
        return Usuario(**dict(fila)) if fila else None

    @staticmethod
    def buscar(usuario_id):
        fila = get_db().execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return Usuario.desde_fila(fila)

    @staticmethod
    def buscar_por_documento(tipo_documento, identificacion):
        fila = get_db().execute(
            "SELECT * FROM usuarios WHERE tipo_documento = ? AND identificacion = ?",
            (normalizar_documento(tipo_documento), normalizar_documento(identificacion)),
        ).fetchone()
        return Usuario.desde_fila(fila)

    @staticmethod
    def autenticar(tipo_documento, identificacion, contrasena):
        """Devuelve el usuario si el documento y la contraseña son correctos (RF-02)."""
        usuario = Usuario.buscar_por_documento(tipo_documento, identificacion)
        if usuario and usuario.activo and usuario.comprobar_contrasena(contrasena):
            return usuario
        return None

    @staticmethod
    def existe_administrador():
        return get_db().execute(
            "SELECT 1 FROM usuarios WHERE rol = 'administrador'"
        ).fetchone() is not None

    @staticmethod
    def listar(pagina=1, por_pagina=25):
        return get_db().execute(
            "SELECT id, nombre_completo, correo, rol, activo, password_hash IS NULL AS pendiente"
            " FROM usuarios ORDER BY rol, nombre_completo LIMIT ? OFFSET ?",
            (por_pagina + 1, (pagina - 1) * por_pagina),
        ).fetchall()
