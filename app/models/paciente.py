""" Modelo de pacientes, representa la informacion de los pacientes     
    registrados en el sistema de vacunacion """

from app.utils import texto_requerido, fecha_requerida


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

    def validar(self):
        texto_requerido(self.nombre_completo)
        texto_requerido(self.identificacion)
        fecha_requerida(self.fecha_nacimiento)

        return True