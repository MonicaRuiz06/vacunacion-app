""" Modelo de pacientes, representa la informacion de los pacientes
    registrados en el sistema de vacunacion """

from app.db import get_db
from app.models.auditoria import registrar_auditoria
from app.models.usuario import (
    Usuario,
    revisar_duplicados,
    revisar_identidad,
    validar_contrasena,
)
from app.utils import ErroresFormulario, calcular_edad, fecha_requerida

CAMPOS_OPCIONALES = ("genero", "telefono", "direccion", "municipio")
CAMPOS_DE_ACCESO = ("tipo_documento", "identificacion", "correo")


class Paciente:
    def __init__(
        self,
        id=None,
        nombre_completo="",
        identificacion="",
        fecha_nacimiento="",
        genero=None,
        telefono=None,
        correo=None,
        direccion=None,
        municipio=None,
        tipo_documento="CC",
        declaracion_responsable=None,
        usuario_id=None,
    ):
        self.id = id
        self.nombre_completo = nombre_completo
        self.identificacion = identificacion
        self.fecha_nacimiento = fecha_nacimiento
        self.genero = genero
        self.telefono = telefono
        self.correo = correo
        self.direccion = direccion
        self.municipio = municipio
        self.tipo_documento = tipo_documento
        self.declaracion_responsable = declaracion_responsable  # fecha de la declaración
        self.usuario_id = usuario_id

    def validar(self):
        errores = revisar_identidad(self)

        try:
            fecha_requerida(self.fecha_nacimiento)
            edad = calcular_edad(self.fecha_nacimiento)
            if edad < 16:
                errores["fecha_nacimiento"] = "El registro está disponible desde los 16 años."
            elif edad < 18 and not self.declaracion_responsable:
                errores["declaracion_responsable"] = (
                    "Si tienes 16 o 17 años, declara que tu responsable te autorizó."
                )
        except ValueError:
            errores["fecha_nacimiento"] = "Escribe una fecha de nacimiento válida."

        for campo in CAMPOS_OPCIONALES:
            valor = (getattr(self, campo) or "").strip()
            if len(valor) > 200:
                errores[campo] = "Máximo 200 caracteres."
            setattr(self, campo, valor or None)

        if errores:
            raise ErroresFormulario(errores)
        return True

    def guardar(self, contrasena):
        """Registra al paciente con su cuenta de acceso (RF-01)."""
        errores = {}
        try:
            self.validar()
        except ErroresFormulario as error:
            errores = error.errores
        if validar_contrasena(contrasena):
            errores["contrasena"] = validar_contrasena(contrasena)
        if not errores:
            errores = revisar_duplicados(self)
        if errores:
            raise ErroresFormulario(errores)

        db = get_db()
        with db:
            usuario = Usuario(
                nombre_completo=self.nombre_completo,
                tipo_documento=self.tipo_documento,
                identificacion=self.identificacion,
                correo=self.correo,
                rol="paciente",
            )
            self.usuario_id = usuario.insertar(contrasena)
            cursor = db.execute(
                "INSERT INTO pacientes (usuario_id, fecha_nacimiento, genero, telefono,"
                " direccion, municipio, declaracion_responsable) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.usuario_id, self.fecha_nacimiento, self.genero, self.telefono,
                 self.direccion, self.municipio, self.declaracion_responsable),
            )
            self.id = cursor.lastrowid
        return self.id

    def datos(self):
        """Datos visibles del perfil, para comparar antes y después."""
        campos = ("nombre_completo", "fecha_nacimiento") + CAMPOS_DE_ACCESO + CAMPOS_OPCIONALES
        return {campo: getattr(self, campo) for campo in campos}

    def actualizar(self):
        """Guarda cambios del perfil (RF-07).

        Devuelve True si cambió el documento o el correo: en ese caso se
        cierran todas las sesiones y el paciente debe ingresar de nuevo (RF-44).
        """
        self.validar()
        errores = revisar_duplicados(self, self.usuario_id)
        if errores:
            raise ErroresFormulario(errores)

        antes = Paciente.buscar_por_usuario(self.usuario_id).datos()
        despues = self.datos()
        cambio_acceso = any(antes[campo] != despues[campo] for campo in CAMPOS_DE_ACCESO)

        db = get_db()
        with db:
            db.execute(
                "UPDATE usuarios SET nombre_completo = ?, tipo_documento = ?, identificacion = ?,"
                " correo = ? WHERE id = ?",
                (self.nombre_completo, self.tipo_documento, self.identificacion, self.correo,
                 self.usuario_id),
            )
            db.execute(
                "UPDATE pacientes SET fecha_nacimiento = ?, genero = ?, telefono = ?,"
                " direccion = ?, municipio = ?, declaracion_responsable = ? WHERE id = ?",
                (self.fecha_nacimiento, self.genero, self.telefono, self.direccion,
                 self.municipio, self.declaracion_responsable, self.id),
            )
            registrar_auditoria(self.usuario_id, "perfil_actualizado", "pacientes", self.id,
                                {"antes": antes, "despues": despues})
            if cambio_acceso:
                Usuario.buscar(self.usuario_id).cerrar_sesiones()
        return cambio_acceso

    @staticmethod
    def buscar_por_usuario(usuario_id):
        fila = get_db().execute(
            "SELECT p.*, u.nombre_completo, u.tipo_documento, u.identificacion, u.correo"
            " FROM pacientes p JOIN usuarios u ON u.id = p.usuario_id WHERE p.usuario_id = ?",
            (usuario_id,),
        ).fetchone()
        return Paciente(**dict(fila)) if fila else None
