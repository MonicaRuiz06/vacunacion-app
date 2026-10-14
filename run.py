"""Punto de entrada para ejecutar la aplicación.

    python run.py               servidor de desarrollo (debug, solo este equipo)
    python run.py --produccion  servidor de Flask sin debug (Windows, Linux y Android)

En producción, HOST y PORT se toman del entorno (por defecto 0.0.0.0:5000,
es decir, visible para otros equipos de la red).
"""

import os
import sys

from app import create_app

app = create_app()


if __name__ == "__main__":
    if "--produccion" in sys.argv[1:]:
        # Sin debug los correos no se muestran en la terminal: sin servidor de
        # correo, las invitaciones y la recuperación de contraseña se pierden.
        if not app.config.get("MAIL_SERVER"):
            print("AVISO: no hay correo configurado (MAIL_SERVER en .env); "
                  "no llegarán invitaciones ni enlaces de recuperación.", flush=True)
        # Sin debug: el depurador de Flask permite ejecutar código desde el
        # navegador si ocurre un error. threaded atiende varias peticiones a la vez.
        app.run(
            host=os.environ.get("HOST") or "0.0.0.0",
            port=int(os.environ.get("PORT") or 5000),
            debug=False,
            threaded=True,
        )
    else:
        app.run(debug=True)
