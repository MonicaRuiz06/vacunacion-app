"""
Funciones de validacion reutilizables del sistema.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app

ZONA_HORARIA = ZoneInfo("America/Bogota")


def ahora():
    """Fecha y hora actual en Colombia; las pruebas pueden reemplazarla."""
    return datetime.now(ZONA_HORARIA)



def texto_requerido(valor):
    if not valor or not valor.strip():
        raise ValueError("El campo es obligatorio.")
    
    return valor.strip()

def fecha_requerida(valor):
    # Se exige AAAA-MM-DD completo porque las fechas se comparan como texto.
    try:
        datetime.strptime(valor, "%Y-%m-%d")
        if len(valor) != 10:
            raise ValueError
        return valor
    
    except (ValueError, TypeError):
        raise ValueError("La fecha no es valida.")

def hora_requerida(valor):
    # Formato HH:MM de 24 horas; también se compara como texto.
    try:
        datetime.strptime(valor, "%H:%M")
        if len(valor) != 5:
            raise ValueError
        return valor

    except (ValueError, TypeError):
        raise ValueError("La hora no es valida.")

def entero_requerido(valor):
    try:
        return int(valor)
    
    except (ValueError, TypeError):
        raise ValueError("Debe ingresar un numero entero.")


class ErroresFormulario(ValueError):
    """Errores de validación de un formulario: {"campo": "mensaje"}."""

    def __init__(self, errores):
        super().__init__("Revisa los campos marcados.")
        self.errores = errores


def calcular_edad(fecha_nacimiento):
    """Años cumplidos hoy (en Colombia) por alguien nacido en esa fecha ISO."""
    nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
    hoy = ahora().date()
    cumplio_este_anio = (hoy.month, hoy.day) >= (nacimiento.month, nacimiento.day)
    return hoy.year - nacimiento.year - (0 if cumplio_este_anio else 1)


def enviar_correo(destino, asunto, texto):
    """Envía un correo y devuelve True si salió.

    En pruebas se guarda en la lista CORREOS_ENVIADOS de la configuración.
    El envío SMTP real se configura en M06; mientras tanto, en modo debug el
    mensaje se muestra en la consola para poder probar los enlaces.
    """
    enviados = current_app.config.get("CORREOS_ENVIADOS")
    if enviados is not None:
        enviados.append({"destino": destino, "asunto": asunto, "texto": texto})
        return True
    if current_app.debug:
        print(f"--- Correo para {destino}: {asunto}\n{texto}\n---")
    return False
