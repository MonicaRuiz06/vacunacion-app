"""
Funciones de validacion reutilizables del sistema.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

ZONA_HORARIA = ZoneInfo("America/Bogota")


def ahora():
    """Fecha y hora actual en Colombia; las pruebas pueden reemplazarla."""
    return datetime.now(ZONA_HORARIA)



def texto_requerido(valor):
    if not valor or not valor.strip():
        raise ValueError("El campo es obligatorio.")
    
    return valor.strip()

def fecha_requerida(valor):
    try:
        datetime.strptime(valor, "%Y-%m-%d")
        return valor
    
    except (ValueError, TypeError):
        raise ValueError("La fecha no es valida.")

def entero_requerido(valor):
    try:
        return int(valor)
    
    except (ValueError, TypeError):
        raise ValueError("Debe ingresar un numero entero.")
