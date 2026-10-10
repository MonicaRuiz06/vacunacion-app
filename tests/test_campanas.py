"""Pruebas del modelo de catálogos, campañas y franjas (M04): RF-09–12, 23, 25, 29, 41."""

from datetime import timedelta

import pytest

from app.db import get_db
from app.models.campana import Campana
from app.models.franja import Franja
from app.models.lote import Lote
from app.models.punto import Punto
from app.models.vacuna import Vacuna
from app.utils import ErroresFormulario
from tests.conftest import (
    crear_campana,
    crear_cita,
    crear_franja,
    crear_paciente,
    crear_punto,
    crear_usuario,
    crear_vacuna,
)

# Hoy, según el reloj fijo de las pruebas, es 2026-10-08.


@pytest.fixture
def admin(app, reloj):
    return crear_usuario(app, "administrador")


@pytest.fixture
def base(app, admin):
    """Un punto, una vacuna, una franja y una campaña en borrador con ambos."""
    punto = crear_punto(app)
    vacuna = crear_vacuna(app)
    franja = crear_franja(app, punto)
    campana = crear_campana(app, admin, puntos=[punto], vacunas=[vacuna])
    return {"punto": punto, "vacuna": vacuna, "franja": franja, "campana": campana}


# Puntos


def test_punto_valido_se_guarda(app, reloj):
    with app.app_context():
        punto_id = Punto(nombre="Punto Campus", direccion="Calle 5", hora_apertura="08:00",
                         hora_cierre="16:00", capacidad_diaria="40").guardar()
        assert Punto.buscar(punto_id).capacidad_diaria == 40


@pytest.mark.parametrize("cambios, campo", [
    ({"hora_apertura": "16:00", "hora_cierre": "08:00"}, "hora_cierre"),
    ({"hora_apertura": "8 am"}, "hora_apertura"),
    ({"capacidad_diaria": "0"}, "capacidad_diaria"),
    ({"nombre": ""}, "nombre"),
])
def test_punto_invalido(app, reloj, cambios, campo):
    datos = {"nombre": "Punto Campus", "direccion": "Calle 5", "hora_apertura": "08:00",
             "hora_cierre": "16:00", "capacidad_diaria": "40", **cambios}
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Punto(**datos).guardar()
    assert campo in error.value.errores


def test_rf13_no_cambia_horario_si_deja_franjas_por_fuera(app, reloj):
    punto_id = crear_punto(app)
    crear_franja(app, punto_id, hora_inicio="08:00", hora_fin="08:30")
    with app.app_context():
        punto = Punto.buscar(punto_id)
        punto.hora_apertura = "09:00"
        with pytest.raises(ValueError):
            punto.guardar()
        punto.hora_apertura = "07:00"
        punto.guardar()
        assert Punto.buscar(punto_id).hora_apertura == "07:00"


# Vacunas y lotes


def test_rf29_vacuna_exige_dosis_positivas(app, reloj):
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Vacuna(nombre="Influenza", dosis_requeridas="0").guardar()
    assert "dosis_requeridas" in error.value.errores


def test_rf29_no_baja_dosis_por_debajo_de_las_aplicadas(app, reloj):
    vacuna_id = crear_vacuna(app, dosis_requeridas=3)
    punto_id = crear_punto(app)
    usuario_id = crear_paciente(app)
    with app.app_context():
        db = get_db()
        paciente_id = db.execute("SELECT id FROM pacientes WHERE usuario_id = ?", (usuario_id,)).fetchone()[0]
        db.execute(
            "INSERT INTO dosis_aplicadas (paciente_id, vacuna_id, punto_id, numero_dosis, fecha_aplicacion)"
            " VALUES (?, ?, ?, 2, '2026-10-01')", (paciente_id, vacuna_id, punto_id))
        db.commit()
        vacuna = Vacuna.buscar(vacuna_id)
        vacuna.dosis_requeridas = "1"
        with pytest.raises(ErroresFormulario):
            vacuna.guardar()
        vacuna.dosis_requeridas = "2"
        vacuna.guardar()


def test_rf23_lote_separado_de_la_vacuna(app, reloj):
    vacuna_id = crear_vacuna(app)
    otra_id = crear_vacuna(app, nombre="Hepatitis B")
    with app.app_context():
        Lote(vacuna_id=vacuna_id, codigo="L-2041", fecha_vencimiento="2026-11-30").guardar()
        Lote(vacuna_id=otra_id, codigo="L-2041", fecha_vencimiento="2026-11-30").guardar()
        with pytest.raises(ErroresFormulario) as error:
            Lote(vacuna_id=vacuna_id, codigo=" L-2041 ", fecha_vencimiento="2026-12-30").guardar()
        assert "codigo" in error.value.errores
        assert len(Lote.listar()) == 2


def test_rf25_lote_sirve_hasta_su_fecha_de_vencimiento(app, reloj):
    vacuna_id = crear_vacuna(app)
    with app.app_context():
        hoy = Lote(vacuna_id=vacuna_id, codigo="HOY", fecha_vencimiento="2026-10-08")
        ayer = Lote(vacuna_id=vacuna_id, codigo="AYER", fecha_vencimiento="2026-10-07")
        assert not hoy.vencido()
        assert ayer.vencido()


def test_lote_de_vacuna_inexistente(app, reloj):
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Lote(vacuna_id="999", codigo="L1", fecha_vencimiento="2026-11-30").guardar()
    assert "vacuna_id" in error.value.errores


# Franjas (RF-11, RF-12, RF-41)


def test_rf11_franja_valida(app, reloj):
    punto_id = crear_punto(app)
    franja_id = crear_franja(app, punto_id)
    with app.app_context():
        franja = Franja.buscar(franja_id)
    assert (franja.hora_inicio, franja.hora_fin, franja.cupos) == ("09:00", "09:30", 5)


@pytest.mark.parametrize("cambios, campo", [
    ({"hora_inicio": "07:30", "hora_fin": "08:30"}, "hora_inicio"),
    ({"hora_inicio": "15:30", "hora_fin": "16:30"}, "hora_fin"),
    ({"hora_inicio": "10:00", "hora_fin": "10:00"}, "hora_fin"),
    ({"cupos": "0"}, "cupos"),
    ({"fecha": "2026-13-01"}, "fecha"),
])
def test_rf11_franja_invalida(app, reloj, cambios, campo):
    punto_id = crear_punto(app)
    datos = {"punto_id": punto_id, "fecha": "2026-11-14", "hora_inicio": "09:00",
             "hora_fin": "09:30", "cupos": "5", **cambios}
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Franja(**datos).guardar()
    assert campo in error.value.errores


def test_rf11_franjas_no_se_superponen_en_el_mismo_punto(app, reloj):
    punto_id = crear_punto(app)
    otro_punto = crear_punto(app, "Punto Centro")
    crear_franja(app, punto_id, hora_inicio="09:00", hora_fin="09:30")
    crear_franja(app, punto_id, hora_inicio="09:30", hora_fin="10:00")  # contigua: válida
    crear_franja(app, otro_punto, hora_inicio="09:00", hora_fin="09:30")  # otro punto: válida
    crear_franja(app, punto_id, fecha="2026-11-15", hora_inicio="09:00", hora_fin="09:30")
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Franja(punto_id=punto_id, fecha="2026-11-14", hora_inicio="09:15",
                   hora_fin="09:45", cupos=5).guardar()
    assert "hora_inicio" in error.value.errores


def test_rf11_rf41_cupos_compartidos_entre_campanas(app, admin, base):
    otra = crear_campana(app, admin, puntos=[base["punto"]], vacunas=[base["vacuna"]], nombre="Otra")
    estados = ["reservada", "presente", "aplicada", "no_aplicada", "registro_anulado",
               "cancelada", "no_asistio"]
    for numero, estado in enumerate(estados):
        usuario_id = crear_paciente(app, identificacion=f"10{numero}", correo=f"p{numero}@example.com")
        campana = base["campana"] if numero % 2 else otra
        crear_cita(app, usuario_id, campana, base["vacuna"], base["franja"], estado)
    with app.app_context():
        # Cancelada y no asistió liberan el cupo; los otros cinco lo ocupan.
        assert Franja.buscar(base["franja"]).ocupados() == 5


def test_rf12_reducir_cupos_hasta_la_ocupacion(app, admin, base):
    for numero in range(3):
        usuario_id = crear_paciente(app, identificacion=f"10{numero}", correo=f"p{numero}@example.com")
        crear_cita(app, usuario_id, base["campana"], base["vacuna"], base["franja"])
    with app.app_context():
        franja = Franja.buscar(base["franja"])
        with pytest.raises(ValueError):
            franja.cambiar_cupos("2")
        assert Franja.buscar(base["franja"]).cupos == 5
        franja.cambiar_cupos("3")
        assert Franja.buscar(base["franja"]).cupos == 3


# Campañas (RF-09, RF-10)


def test_rf10_campana_nueva_queda_en_borrador(app, base):
    with app.app_context():
        campana = Campana.buscar(base["campana"])
    assert campana.estado == "borrador"
    assert campana.puntos_ids == [base["punto"]]
    assert campana.vacunas_ids == [base["vacuna"]]


@pytest.mark.parametrize("cambios, campo", [
    ({"nombre": ""}, "nombre"),
    ({"descripcion": ""}, "descripcion"),
    ({"fecha_inicio": "2026-11-20", "fecha_fin": "2026-11-10"}, "fecha_fin"),
])
def test_rf09_campana_invalida(app, admin, cambios, campo):
    datos = {"nombre": "Jornada", "descripcion": "Ficticia", "fecha_inicio": "2026-11-10",
             "fecha_fin": "2026-11-20", **cambios}
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Campana(**datos).guardar(admin)
    assert campo in error.value.errores


def test_rf09_publicar_completa(app, admin, base):
    with app.app_context():
        campana = Campana.buscar(base["campana"])
        campana.publicar(admin)
        assert Campana.buscar(base["campana"]).estado == "publicada"


@pytest.mark.parametrize("faltante", ["puntos", "vacunas", "franja"])
def test_rf09_publicar_incompleta_falla(app, admin, faltante):
    punto = crear_punto(app)
    vacuna = crear_vacuna(app)
    if faltante != "franja":
        crear_franja(app, punto)
    campana_id = crear_campana(
        app, admin,
        puntos=[] if faltante == "puntos" else [punto],
        vacunas=[] if faltante == "vacunas" else [vacuna],
    )
    with app.app_context():
        with pytest.raises(ValueError):
            Campana.buscar(campana_id).publicar(admin)
        assert Campana.buscar(campana_id).estado == "borrador"


def test_rf09_franja_fuera_de_las_fechas_no_cuenta(app, admin):
    punto = crear_punto(app)
    vacuna = crear_vacuna(app)
    crear_franja(app, punto, fecha="2026-12-01")
    campana_id = crear_campana(app, admin, puntos=[punto], vacunas=[vacuna])
    with app.app_context():
        with pytest.raises(ValueError):
            Campana.buscar(campana_id).publicar(admin)


def test_rf10_pausar_conserva_citas_y_reanudar(app, admin, base):
    usuario_id = crear_paciente(app)
    cita_id = crear_cita(app, usuario_id, base["campana"], base["vacuna"], base["franja"])
    with app.app_context():
        campana = Campana.buscar(base["campana"])
        campana.publicar(admin)
        campana.pausar(admin)
        assert Campana.buscar(base["campana"]).estado == "pausada"
        estado = get_db().execute("SELECT estado FROM citas WHERE id = ?", (cita_id,)).fetchone()[0]
        assert estado == "reservada"
        campana.reanudar(admin)
        assert Campana.buscar(base["campana"]).estado == "publicada"


def test_rf10_transiciones_no_permitidas(app, admin, base):
    with app.app_context():
        campana = Campana.buscar(base["campana"])
        with pytest.raises(ValueError):
            campana.pausar(admin)  # borrador
        with pytest.raises(ValueError):
            campana.reanudar(admin)  # borrador


def test_rf09_campana_vencida_queda_finalizada(app, admin, base, reloj):
    with app.app_context():
        campana = Campana.buscar(base["campana"])
        campana.publicar(admin)
        campana.pausar(admin)
        reloj["ahora"] += timedelta(days=60)  # ya pasó el 2026-11-20
        Campana.finalizar_vencidas()
        campana = Campana.buscar(base["campana"])
        assert campana.estado == "finalizada"
        with pytest.raises(ValueError):
            campana.reanudar(admin)


def test_rf13_editar_sin_afectar_citas(app, admin, base):
    with app.app_context():
        campana = Campana.buscar(base["campana"])
        campana.nombre = "Jornada de bienestar 2026"
        campana.guardar(admin)
        assert Campana.buscar(base["campana"]).nombre == "Jornada de bienestar 2026"
        acciones = [fila["accion"] for fila in get_db().execute("SELECT accion FROM auditoria")]
    assert acciones == ["campana_creada", "campana_editada"]


def test_rf13_editar_que_deja_citas_activas_por_fuera_se_rechaza(app, admin, base):
    otra_vacuna = crear_vacuna(app, nombre="Tétanos")
    usuario_id = crear_paciente(app)
    crear_cita(app, usuario_id, base["campana"], base["vacuna"], base["franja"])
    with app.app_context():
        campana = Campana.buscar(base["campana"])
        campana.vacunas_ids = [otra_vacuna]
        with pytest.raises(ValueError):
            campana.guardar(admin)
        campana = Campana.buscar(base["campana"])
        campana.fecha_inicio = "2026-11-15"  # la franja es del 14
        with pytest.raises(ValueError):
            campana.guardar(admin)
        assert Campana.buscar(base["campana"]).vacunas_ids == [base["vacuna"]]


def test_rf13_cita_cancelada_no_bloquea_cambios(app, admin, base):
    otra_vacuna = crear_vacuna(app, nombre="Tétanos")
    usuario_id = crear_paciente(app)
    crear_cita(app, usuario_id, base["campana"], base["vacuna"], base["franja"], "cancelada")
    with app.app_context():
        campana = Campana.buscar(base["campana"])
        campana.vacunas_ids = [otra_vacuna]
        campana.guardar(admin)


def test_listar_solo_publicadas(app, admin, base):
    crear_campana(app, admin, nombre="Borrador")
    with app.app_context():
        Campana.buscar(base["campana"]).publicar(admin)
        nombres = [campana.nombre for campana in Campana.listar(solo_publicadas=True)]
    assert nombres == ["Jornada de bienestar"]


# Fechas al crear (hoy es 2026-10-08 en las pruebas)


def test_campana_nueva_no_empieza_antes_de_hoy(app, admin):
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Campana(nombre="Jornada", descripcion="Ficticia", fecha_inicio="2026-10-07",
                    fecha_fin="2026-10-20").guardar(admin)
        assert "fecha_inicio" in error.value.errores
        Campana(nombre="Jornada", descripcion="Ficticia", fecha_inicio="2026-10-08",
                fecha_fin="2026-10-08").guardar(admin)


def test_campana_nueva_no_termina_antes_de_hoy(app, admin):
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Campana(nombre="Jornada", descripcion="Ficticia", fecha_inicio="2026-10-01",
                    fecha_fin="2026-10-05").guardar(admin)
    assert "fecha_inicio" in error.value.errores


def test_campana_que_ya_empezo_se_puede_editar(app, admin, base, reloj):
    reloj["ahora"] += timedelta(days=5)  # 2026-11-13: ya empezó el 2026-11-10
    with app.app_context():
        campana = Campana.buscar(base["campana"])
        campana.descripcion = "Descripción corregida"
        campana.guardar(admin)
        assert Campana.buscar(base["campana"]).descripcion == "Descripción corregida"
