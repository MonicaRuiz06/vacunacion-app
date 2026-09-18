"""
Modelo de pacientes, representa la información de los pacientes
registrados en el sistema de vacunación
"""


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
        municipio=None
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

    def validar_datos(self):
        if not self.nombre_completo:
            return "El nombre del paciente es obligatorio."
        elif not self.identificacion:
            return "La identificación del paciente es obligatoria."
        elif not self.fecha_nacimiento:
            return "La fecha de nacimiento es obligatoria."
        else:
            return "Los datos del paciente son válidos."