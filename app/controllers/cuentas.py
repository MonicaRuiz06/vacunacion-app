"""Rutas de cuentas: registro, ingreso, perfil, recuperación y vacunadores."""

from functools import wraps

import click
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from app.db import get_db
from app.models.paciente import Paciente
from app.models.usuario import Usuario, crear_token, listar_puntos, usar_token
from app.utils import ErroresFormulario, ahora, enviar_correo

bp = Blueprint("cuentas", __name__, cli_group=None)


# --- Sesión y permisos --------------------------------------------------------


@bp.before_app_request
def cargar_usuario():
    """Deja en g.usuario la cuenta de la sesión, o None.

    La sesión se descarta si la cuenta se desactivó, si cambió su documento,
    correo o contraseña (la versión ya no coincide, RF-44) o si es otra cuenta
    con el mismo id (por ejemplo, después de borrar la base local).
    """
    g.usuario = None
    usuario_id = session.get("usuario_id")
    if usuario_id is None:
        return
    usuario = Usuario.buscar(usuario_id)
    if (
        usuario
        and usuario.activo
        and usuario.version_credenciales == session.get("version")
        and usuario.creado_en == session.get("creado_en")
    ):
        g.usuario = usuario
    else:
        session.clear()


def rol_requerido(*roles):
    """Exige sesión iniciada y, si se indican, uno de esos roles."""

    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if g.usuario is None:
                flash("Inicia sesión para continuar.", "info")
                return redirect(url_for("cuentas.ingresar"))
            if roles and g.usuario.rol not in roles:
                abort(403)
            return vista(*args, **kwargs)

        return envoltura

    return decorador


def enviar_enlace(usuario, proposito, token):
    """Envía por correo el enlace de recuperación o de invitación."""
    if proposito == "recuperacion":
        ruta, asunto = "cuentas.restablecer", "Recupera tu contraseña"
    else:
        ruta, asunto = "cuentas.invitacion", "Invitación al sistema de vacunación"
    enlace = url_for(ruta, token=token, _external=True)
    texto = (
        f"Hola, {usuario.nombre_completo}.\n\n"
        f"Usa este enlace para establecer tu contraseña: {enlace}\n\n"
        "El enlace vence en 30 minutos y solo sirve una vez."
    )
    return enviar_correo(usuario.correo, asunto, texto)


# --- Registro e ingreso -------------------------------------------------------


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    errores = {}
    if request.method == "POST":
        formulario = request.form
        paciente = Paciente(
            nombre_completo=formulario.get("nombre_completo"),
            tipo_documento=formulario.get("tipo_documento"),
            identificacion=formulario.get("identificacion"),
            correo=formulario.get("correo"),
            fecha_nacimiento=formulario.get("fecha_nacimiento"),
            genero=formulario.get("genero"),
            telefono=formulario.get("telefono"),
            direccion=formulario.get("direccion"),
            municipio=formulario.get("municipio"),
            declaracion_responsable=(
                ahora().date().isoformat() if formulario.get("declaracion_responsable") else None
            ),
        )
        try:
            paciente.guardar(formulario.get("contrasena"))
            flash("Tu cuenta está lista. Ya puedes iniciar sesión.", "exito")
            return redirect(url_for("cuentas.ingresar"), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
    return render_template("cuentas/registro.html", valores=request.form, errores=errores), (
        400 if errores else 200
    )


@bp.route("/ingresar", methods=["GET", "POST"])
def ingresar():
    if request.method == "POST":
        usuario = Usuario.autenticar(
            request.form.get("tipo_documento"),
            request.form.get("identificacion"),
            request.form.get("contrasena"),
        )
        if usuario:
            session.clear()
            session.permanent = True  # dura PERMANENT_SESSION_LIFETIME (8 horas)
            session["usuario_id"] = usuario.id
            session["version"] = usuario.version_credenciales
            session["creado_en"] = usuario.creado_en
            return redirect(url_for("cuentas.perfil"), 303)
        flash("Documento o contraseña incorrectos.", "error")
        return render_template("cuentas/ingresar.html", valores=request.form, errores={}), 400
    return render_template("cuentas/ingresar.html", valores={}, errores={})


@bp.route("/salir", methods=["POST"])
def salir():
    session.clear()
    flash("Cerraste sesión.", "info")
    return redirect(url_for("cuentas.ingresar"), 303)


# --- Recuperación e invitación (RF-05, RF-06) -----------------------------------


@bp.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if request.method == "POST":
        usuario = Usuario.buscar_por_documento(
            request.form.get("tipo_documento"), request.form.get("identificacion")
        )
        if usuario and usuario.activo and usuario.password_hash:
            with get_db():
                token = crear_token(usuario.id, "recuperacion")
            enviar_enlace(usuario, "recuperacion", token)
        # Misma respuesta exista o no la cuenta, para no revelar quién está registrado.
        flash("Si la cuenta existe, enviamos un enlace a su correo. Vence en 30 minutos.", "info")
        return redirect(url_for("cuentas.recuperar"), 303)
    return render_template("cuentas/recuperar.html", valores={}, errores={})


def establecer_contrasena(proposito, titulo):
    """Formulario común de /restablecer y /invitacion."""
    token = request.args.get("token", "")
    errores = {}
    if request.method == "POST":
        try:
            usar_token(token, proposito, request.form.get("contrasena_nueva"))
            session.clear()
            flash("Contraseña guardada. Ya puedes iniciar sesión.", "exito")
            return redirect(url_for("cuentas.ingresar"), 303)
        except ErroresFormulario as error:
            errores = error.errores
        except ValueError as error:
            flash(str(error), "error")
            errores = {"token": str(error)}
    return render_template("cuentas/contrasena_nueva.html", titulo=titulo, errores=errores), (
        400 if errores else 200
    )


@bp.route("/restablecer", methods=["GET", "POST"])
def restablecer():
    return establecer_contrasena("recuperacion", "Nueva contraseña")


@bp.route("/invitacion", methods=["GET", "POST"])
def invitacion():
    return establecer_contrasena("invitacion", "Activa tu cuenta de vacunador")


# --- Perfil (RF-07, RF-44) ----------------------------------------------------


@bp.route("/perfil", methods=["GET", "POST"])
@rol_requerido()
def perfil():
    if g.usuario.rol != "paciente":
        if request.method == "POST":
            abort(403)  # el personal no edita su identidad desde el perfil
        return render_template("cuentas/perfil.html", paciente=None, valores={}, errores={})

    paciente = Paciente.buscar_por_usuario(g.usuario.id)
    errores = {}
    if request.method == "POST":
        formulario = request.form
        for campo in ("nombre_completo", "tipo_documento", "identificacion", "correo",
                      "fecha_nacimiento", "genero", "telefono", "direccion", "municipio"):
            setattr(paciente, campo, formulario.get(campo))
        if formulario.get("declaracion_responsable") and not paciente.declaracion_responsable:
            paciente.declaracion_responsable = ahora().date().isoformat()
        try:
            if paciente.actualizar():
                session.clear()
                flash("Cambiaste tu documento o correo: inicia sesión de nuevo.", "info")
                return redirect(url_for("cuentas.ingresar"), 303)
            flash("Perfil actualizado.", "exito")
            return redirect(url_for("cuentas.perfil"), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
    valores = request.form if request.method == "POST" else vars(paciente)
    return render_template("cuentas/perfil.html", paciente=paciente, valores=valores,
                           errores=errores), (400 if errores else 200)


@bp.route("/perfil/contrasena", methods=["GET", "POST"])
@rol_requerido()
def cambiar_contrasena():
    errores = {}
    if request.method == "POST":
        try:
            g.usuario.cambiar_contrasena(
                request.form.get("contrasena_actual"), request.form.get("contrasena_nueva")
            )
            session.clear()
            flash("Contraseña cambiada. Cerramos todas tus sesiones: ingresa de nuevo.", "exito")
            return redirect(url_for("cuentas.ingresar"), 303)
        except ErroresFormulario as error:
            errores = error.errores
    return render_template("cuentas/cambiar_contrasena.html", errores=errores), (
        400 if errores else 200
    )


# --- Administración de vacunadores (RF-06) --------------------------------------


def buscar_vacunador(usuario_id):
    usuario = Usuario.buscar(usuario_id)
    if usuario is None or usuario.rol != "vacunador":
        abort(404)
    return usuario


@bp.route("/usuarios")
@rol_requerido("administrador")
def usuarios():
    pagina = max(request.args.get("pagina", 1, type=int), 1)
    filas = Usuario.listar(pagina)
    return render_template("cuentas/usuarios.html", usuarios=filas[:25], pagina=pagina,
                           hay_siguiente=len(filas) > 25)


@bp.route("/usuarios/vacunador", methods=["GET", "POST"])
@rol_requerido("administrador")
def nuevo_vacunador():
    errores = {}
    if request.method == "POST":
        vacunador = Usuario(
            nombre_completo=request.form.get("nombre_completo"),
            tipo_documento=request.form.get("tipo_documento"),
            identificacion=request.form.get("identificacion"),
            correo=request.form.get("correo"),
        )
        try:
            token = vacunador.invitar(request.form.getlist("puntos"), g.usuario.id)
            if enviar_enlace(vacunador, "invitacion", token):
                flash("Vacunador invitado. Recibirá un enlace en su correo.", "exito")
            else:
                flash("Vacunador creado, pero el correo no se pudo enviar. "
                      "Renueva la invitación cuando el correo esté configurado.", "error")
            return redirect(url_for("cuentas.usuarios"), 303)
        except ErroresFormulario as error:
            errores = error.errores
            flash(str(error), "error")
    return render_template("cuentas/vacunador.html", valores=request.form, errores=errores,
                           puntos=listar_puntos(), elegidos=request.form.getlist("puntos")), (
        400 if errores else 200
    )


@bp.route("/usuarios/<int:usuario_id>/puntos", methods=["GET", "POST"])
@rol_requerido("administrador")
def puntos_vacunador(usuario_id):
    vacunador = buscar_vacunador(usuario_id)
    if request.method == "POST":
        try:
            vacunador.asignar_puntos(request.form.getlist("puntos"), g.usuario.id)
            flash("Puntos actualizados.", "exito")
            return redirect(url_for("cuentas.usuarios"), 303)
        except ValueError as error:
            flash(str(error), "error")
    elegidos = [str(punto["id"]) for punto in vacunador.puntos()]
    return render_template("cuentas/puntos.html", vacunador=vacunador,
                           puntos=listar_puntos(), elegidos=elegidos)


@bp.route("/usuarios/<int:usuario_id>/invitacion", methods=["POST"])
@rol_requerido("administrador")
def renovar_invitacion(usuario_id):
    vacunador = buscar_vacunador(usuario_id)
    if vacunador.password_hash:
        flash("Este vacunador ya activó su cuenta.", "info")
        return redirect(url_for("cuentas.usuarios"), 303)
    with get_db():
        token = crear_token(vacunador.id, "invitacion")  # borra el enlace anterior
    if enviar_enlace(vacunador, "invitacion", token):
        flash("Invitación renovada. El enlace anterior ya no sirve.", "exito")
    else:
        flash("No se pudo enviar el correo de invitación.", "error")
    return redirect(url_for("cuentas.usuarios"), 303)


# --- Administrador inicial ----------------------------------------------------


@bp.cli.command("crear-admin")
@click.option("--nombre", prompt="Nombre completo")
@click.option("--tipo", prompt="Tipo de documento (CC, CE o PASAPORTE)")
@click.option("--documento", prompt="Número de documento")
@click.option("--correo", prompt="Correo")
@click.password_option("--contrasena", prompt="Contraseña", confirmation_prompt="Repite la contraseña")
def crear_admin(nombre, tipo, documento, correo, contrasena):
    """Crea el primer administrador (sin credenciales en el repositorio)."""
    if Usuario.existe_administrador():
        click.echo("Ya existe un administrador.")
        return
    admin = Usuario(nombre_completo=nombre, tipo_documento=tipo, identificacion=documento,
                    correo=correo, rol="administrador")
    try:
        admin.guardar(contrasena)
        click.echo("Administrador creado.")
    except ErroresFormulario as error:
        for mensaje in error.errores.values():
            click.echo(f"- {mensaje}")
