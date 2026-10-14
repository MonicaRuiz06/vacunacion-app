"""
Funciones de validacion reutilizables del sistema.
"""

import smtplib
from datetime import datetime
from email.message import EmailMessage
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


DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")


def fecha_larga(fecha_iso):
    """'2026-11-14' -> 'sábado 14 de noviembre de 2026' (filtro de plantilla)."""
    if not fecha_iso:
        return ""
    fecha = datetime.strptime(fecha_iso, "%Y-%m-%d")
    return f"{DIAS[fecha.weekday()]} {fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"


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
    """Envía un correo por SMTP y devuelve True si salió.

    El servidor se configura con variables de entorno (ver config.py). En
    pruebas, si existe la lista CORREOS_ENVIADOS, el correo se guarda ahí.
    Sin servidor configurado no se finge el envío: devuelve False y, en modo
    debug, muestra el mensaje en la consola para poder probar los enlaces.
    """
    config = current_app.config
    enviados = config.get("CORREOS_ENVIADOS")
    if enviados is not None:
        enviados.append({"destino": destino, "asunto": asunto, "texto": texto})
        return True
    if not config.get("MAIL_SERVER"):
        if current_app.debug:
            print(f"--- Correo para {destino}: {asunto}\n{texto}\n---")
        return False

    mensaje = EmailMessage()
    mensaje["From"] = config["MAIL_FROM"]
    mensaje["To"] = destino
    mensaje["Subject"] = asunto
    mensaje.set_content(texto)
    try:
        with smtplib.SMTP(config["MAIL_SERVER"], config["MAIL_PORT"], timeout=10) as servidor:
            if config.get("MAIL_USE_TLS"):
                servidor.starttls()
            if config.get("MAIL_USERNAME"):
                servidor.login(config["MAIL_USERNAME"], config["MAIL_PASSWORD"])
            servidor.send_message(mensaje)
        return True
    except (smtplib.SMTPException, OSError) as error:
        # Solo el tipo de error: nunca credenciales ni el contenido del correo.
        current_app.logger.warning("No se pudo enviar un correo: %s", type(error).__name__)
        return False
