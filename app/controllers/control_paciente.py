"""
Controlador de pacientes.

Contiene las rutas relacionadas con los pacientes
del sistema de vacunación.
"""
from flask import Blueprint

pacientes_bp = Blueprint("pacientes", __name__)
@pacientes_bp.route("/pacientes")
def listar_pacientes():
    return "pacientes: " """ aqui se veran los pacientes """
