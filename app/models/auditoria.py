"""Registro de cambios importantes: quién, qué y cuándo."""

import json

from app.db import get_db
from app.utils import ahora


def registrar_auditoria(actor_id, accion, tabla, registro_id, detalle=None, motivo=None):
    """Agrega una fila a auditoria. No hace commit: lo hace quien llama.

    detalle es un diccionario (por ejemplo {"antes": ..., "despues": ...});
    nunca debe incluir contraseñas ni enlaces.
    """
    get_db().execute(
        "INSERT INTO auditoria (actor_id, accion, tabla, registro_id, detalle, motivo, fecha)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            actor_id,
            accion,
            tabla,
            registro_id,
            json.dumps(detalle, ensure_ascii=False) if detalle else None,
            motivo,
            ahora().isoformat(),
        ),
    )
