"""
Controlador de pacientes.
"""
from flask import Blueprint, render_template, request, redirect, url_for
from app.db import get_db

pacientes_bp = Blueprint("pacientes", __name__)
@pacientes_bp.route("/pacientes")

def listar_pacientes():
    db = get_db()
    pacientes = db.execute(
        "SELECT * FROM pacientes ORDER BY id DESC"
    ).fetchall()
    return render_template(
        "pacientes.html",

        pacientes=pacientes
    )

@pacientes_bp.route("/pacientes/nuevo", methods=["GET", "POST"])
def nuevo_paciente():

    if request.method == "POST":
        nombre_completo = request.form["nombre_completo"]
        identificacion = request.form["identificacion"]
        fecha_nacimiento = request.form["fecha_nacimiento"]
        genero = request.form["genero"]
        telefono = request.form["telefono"]
        correo = request.form["correo"]
        direccion = request.form["direccion"]
        municipio = request.form["municipio"]

        db = get_db()
        db.execute(

        """
        INSERT INTO pacientes

        (nombre_completo,
        identificacion,
        fecha_nacimiento,
        genero,
        telefono,
        correo,
        direccion,
        municipio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
        (nombre_completo,
        identificacion,
        fecha_nacimiento,
        genero,
        telefono,
        correo,
        direccion,
        municipio)
    )
        
        db.commit()
        return redirect(url_for("pacientes.listar_pacientes"))

    return render_template("nuevo_paciente.html")

@pacientes_bp.route("/pacientes/editar/<int:id>", methods=["GET", "POST"])
def editar_paciente(id):
    db = get_db()
    
    paciente = db.execute(
    "SELECT * FROM pacientes WHERE id = ?",
    (id,)
    ).fetchone()
    if paciente is None:
        return "Paciente no encontrado", 404

    if request.method == "POST":

        nombre_completo = request.form["nombre_completo"]
        identificacion = request.form["identificacion"]
        fecha_nacimiento = request.form["fecha_nacimiento"]
        genero = request.form["genero"]
        telefono = request.form["telefono"]
        correo = request.form["correo"]
        direccion = request.form["direccion"]
        municipio = request.form["municipio"]

        db.execute(
        """
        UPDATE pacientes
            SET nombre_completo = ?,
            identificacion = ?,
            fecha_nacimiento = ?,
            genero = ?,
            telefono = ?,
            correo = ?,
            direccion = ?,
            municipio = ?
            WHERE id = ?
        """,
        (
            nombre_completo,
            identificacion,
            fecha_nacimiento,
            genero,
            telefono,
            correo,
            direccion,
            municipio,
            id
        )
        )

        db.commit()
        return redirect(url_for("pacientes.listar_pacientes"))
    
    return render_template(
    "editar_paciente.html",
    paciente=paciente
    )


@pacientes_bp.route("/pacientes/eliminar/<int:id>", methods=["POST"])
def eliminar_paciente(id):
    db = get_db()
    db.execute("DELETE FROM pacientes WHERE id = ?",
        (id,)
    )

    db.commit()

    return redirect(url_for("pacientes.listar_pacientes"))



