"""Pruebas de las plantillas base, mensajes y páginas de error (M00-F)."""

from flask import abort, flash, redirect, render_template_string

from app import create_app


def test_inicio_usa_la_plantilla_base(client):
    html = client.get("/").get_data(as_text=True)
    assert '<html lang="es"' in html
    assert 'href="/"' in html
    assert 'class="pie"' in html


def test_mensaje_flash_se_muestra_despues_de_redirigir(app):
    @app.route("/prueba-mensaje")
    def prueba_mensaje():
        flash("Vacuna registrada.", "exito")
        return redirect("/")

    html = app.test_client().get("/prueba-mensaje", follow_redirects=True).get_data(as_text=True)
    assert "Vacuna registrada." in html
    assert "mensaje exito" in html


def test_pagina_no_encontrada_en_espanol(client):
    respuesta = client.get("/no-existe")
    assert respuesta.status_code == 404
    assert "Página no encontrada" in respuesta.get_data(as_text=True)


def test_sin_permiso_en_espanol(app):
    @app.route("/prueba-permiso")
    def prueba_permiso():
        abort(403)

    respuesta = app.test_client().get("/prueba-permiso")
    assert respuesta.status_code == 403
    assert "No tienes permiso" in respuesta.get_data(as_text=True)


def test_formulario_vencido_muestra_mensaje(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "prueba.db")})
    app.add_url_rule("/formulario", "formulario", lambda: "ok", methods=["POST"])
    respuesta = app.test_client().post("/formulario")
    assert respuesta.status_code == 400
    assert "El formulario venció" in respuesta.get_data(as_text=True)


def test_macro_csrf_agrega_el_campo_oculto(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "prueba.db")})
    with app.test_request_context():
        html = render_template_string(
            "{% from '_formularios.html' import csrf_campo %}{{ csrf_campo() }}"
        )
    assert 'type="hidden" name="csrf_token"' in html


def test_macro_campo_muestra_error(app):
    with app.test_request_context():
        html = render_template_string(
            "{% from '_formularios.html' import campo %}"
            "{{ campo('correo', 'Correo', {'correo': 'ana@'}, {'correo': 'Correo no válido.'}) }}"
        )
    assert 'name="correo"' in html
    assert 'value="ana@"' in html
    assert "Correo no válido." in html
    assert 'aria-invalid="true"' in html
