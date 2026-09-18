""" Modelo de pacientes, representa la informacion de los pacientes     
    registrados en el sistema de vacunacion """

class Paciente:
    def _init_(
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
    