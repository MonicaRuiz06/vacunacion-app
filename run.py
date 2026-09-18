"""
Punto de entrada de la aplicación.

Por ahora solo levanta un Flask mínimo para confirmar que el entorno
de cada integrante está bien configurado. Cuando exista la fábrica de
la app en app/__init__.py (create_app), reemplacen esto por:

    from app import create_app
    app = create_app()

Para probar este archivo tal como está:
    pip install -r requirements.txt
    python run.py
Y abran http://127.0.0.1:5000 en el navegador.
"""

from flask import Flask

app = Flask(__name__)


@app.route("/")
def inicio():
    return "Vacunacion-app: entorno configurado correctamente. Falta construir la aplicación."


if __name__ == "__main__":
    app.run(debug=True)
