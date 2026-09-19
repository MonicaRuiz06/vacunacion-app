"""
Funciones de validacion reutilizables del sistema.
"""

from datetime import datetime


def texto_requerido(valor):
    if not valor or not valor.strip():
        raise ValueError("El campo es obligatorio.")
    
    return valor.strip()

def fecha_requerida(valor):
    try:
        datetime.strptime(valor, "%Y-%m-%d")
        return valor
    
    except ValueError:
        raise ValueError("La fecha no es valida.")

def entero_requerido(valor):
    try:
        return int(valor)
    
    except (ValueError, TypeError):
        raise ValueError("Debe ingresar un numero entero.")

    