"""Pruebas del inventario por lote y la disponibilidad (M05): RF-14, RF-23–26."""

import itertools
import random

import pytest

from app.db import get_db
from app.models.inventario import Inventario, dosis_sin_cubrir, hay_dosis, registrar_entrada
from app.utils import ErroresFormulario
from tests.conftest import (
    crear_campana,
    crear_cita,
    crear_franja,
    crear_lote,
    crear_paciente,
    crear_punto,
    crear_usuario,
    crear_vacuna,
)

# Hoy, según el reloj fijo de las pruebas, es 2026-10-08.


@pytest.fixture
def base(app, reloj):
    admin = crear_usuario(app, "administrador")
    punto = crear_punto(app)
    vacuna = crear_vacuna(app)
    lote = crear_lote(app, vacuna)
    return {"admin": admin, "punto": punto, "vacuna": vacuna, "lote": lote}


def entrada(app, base, cantidad=10, lote=None, clave=None, motivo="Entrega del proveedor"):
    with app.app_context():
        return registrar_entrada(base["punto"], lote or base["lote"], cantidad, motivo,
                                 base["admin"], clave)


def saldo(app, inventario_id):
    with app.app_context():
        return Inventario.buscar(inventario_id).cantidad_disponible


def movimientos(app):
    with app.app_context():
        return get_db().execute(
            "SELECT tipo, cantidad, motivo, usuario_id FROM movimientos_inventario ORDER BY id"
        ).fetchall()


# RF-23 — Entradas


def test_rf23_entrada_crea_saldo_y_movimiento(app, base):
    inventario_id = entrada(app, base, 10)
    assert saldo(app, inventario_id) == 10
    assert [tuple(fila) for fila in movimientos(app)] == [
        ("entrada", 10, "Entrega del proveedor", base["admin"])]


def test_rf23_segunda_entrada_del_mismo_lote_suma(app, base):
    primera = entrada(app, base, 10)
    segunda = entrada(app, base, 5)
    assert primera == segunda
    assert saldo(app, primera) == 15


@pytest.mark.parametrize("cambios, campo", [
    ({"cantidad": "0"}, "cantidad"),
    ({"cantidad": "-3"}, "cantidad"),
    ({"cantidad": "diez"}, "cantidad"),
    ({"motivo": "  "}, "motivo"),
    ({"lote": 999}, "lote_id"),
])
def test_rf23_entrada_invalida(app, base, cambios, campo):
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            registrar_entrada(base["punto"], cambios.get("lote", base["lote"]),
                              cambios.get("cantidad", 5), cambios.get("motivo", "Entrega"),
                              base["admin"])
    assert campo in error.value.errores
    assert movimientos(app) == []


def test_rf23_entrada_en_punto_inexistente(app, base):
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            registrar_entrada(999, base["lote"], 5, "Entrega", base["admin"])
    assert "punto_id" in error.value.errores


def test_misma_clave_no_registra_dos_veces(app, base):
    inventario_id = entrada(app, base, 10, clave="formulario-1")
    entrada(app, base, 10, clave="formulario-1")
    assert saldo(app, inventario_id) == 10
    assert len(movimientos(app)) == 1


# RF-24 — Ajustes


def test_rf24_ajuste_registra_autor_y_motivo(app, base):
    inventario_id = entrada(app, base, 10)
    with app.app_context():
        Inventario.buscar(inventario_id).ajustar("-3", "Dosis dañadas", base["admin"])
        Inventario.buscar(inventario_id).ajustar("2", "Conteo físico", base["admin"])
    assert saldo(app, inventario_id) == 9
    assert [tuple(fila) for fila in movimientos(app)][1:] == [
        ("ajuste", -3, "Dosis dañadas", base["admin"]),
        ("ajuste", 2, "Conteo físico", base["admin"]),
    ]


@pytest.mark.parametrize("cantidad, motivo, campo", [
    ("0", "Conteo", "cantidad"),
    ("abc", "Conteo", "cantidad"),
    ("-1", "", "motivo"),
])
def test_rf24_ajuste_invalido(app, base, cantidad, motivo, campo):
    inventario_id = entrada(app, base, 10)
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Inventario.buscar(inventario_id).ajustar(cantidad, motivo, base["admin"])
    assert campo in error.value.errores
    assert saldo(app, inventario_id) == 10


def test_rf24_ajuste_no_deja_saldo_negativo(app, base):
    inventario_id = entrada(app, base, 3)
    with app.app_context():
        with pytest.raises(ErroresFormulario) as error:
            Inventario.buscar(inventario_id).ajustar("-4", "Pérdida", base["admin"])
    assert "cantidad" in error.value.errores
    assert saldo(app, inventario_id) == 3
    assert len(movimientos(app)) == 1


def test_rnf06_dos_ajustes_sobre_el_mismo_saldo(app, base):
    # Ambos leen saldo 1 antes de ajustar; solo uno puede dejarlo en cero.
    inventario_id = entrada(app, base, 1)
    with app.app_context():
        primero = Inventario.buscar(inventario_id)
        segundo = Inventario.buscar(inventario_id)
        primero.ajustar("-1", "Baja", base["admin"])
        with pytest.raises(ErroresFormulario):
            segundo.ajustar("-1", "Baja", base["admin"])
    assert saldo(app, inventario_id) == 0


def test_si_falla_el_movimiento_no_cambia_el_saldo(app, base):
    inventario_id = entrada(app, base, 5)
    with app.app_context():
        inventario = Inventario.buscar(inventario_id)
        with pytest.raises(Exception):
            inventario.mover(-2, "tipo_inexistente", "Prueba", base["admin"])
    assert saldo(app, inventario_id) == 5


# Disponibilidad (RF-14, RF-25, RF-26)


def reservar(app, base, campana, fecha, numero, estado="reservada", usuario_id=None):
    """Crea una franja en la fecha (si hace falta) y una cita en ella."""
    with app.app_context():
        fila = get_db().execute("SELECT id FROM franjas WHERE punto_id = ? AND fecha = ?",
                                (base["punto"], fecha)).fetchone()
    franja = fila[0] if fila else crear_franja(app, base["punto"], fecha=fecha, cupos=20)
    if usuario_id is None:
        usuario_id = crear_paciente(app, identificacion=f"P{numero}", correo=f"p{numero}@example.com")
    return crear_cita(app, usuario_id, campana, base["vacuna"], franja, estado)


@pytest.fixture
def campana(app, base):
    return crear_campana(app, base["admin"], puntos=[base["punto"]], vacunas=[base["vacuna"]],
                         fecha_inicio="2026-10-01", fecha_fin="2026-12-31")


def disponible(app, base, fecha, excluir=None):
    with app.app_context():
        return hay_dosis(base["punto"], base["vacuna"], fecha, excluir)


def test_rf14_sin_existencias_no_hay_dosis(app, base):
    assert not disponible(app, base, "2026-11-14")


def test_rf14_cada_reserva_ocupa_una_dosis(app, base, campana):
    entrada(app, base, 2)
    reservar(app, base, campana, "2026-11-14", 1)
    assert disponible(app, base, "2026-11-14")
    reservar(app, base, campana, "2026-11-14", 2)
    assert not disponible(app, base, "2026-11-14")


def test_rf14_canceladas_y_cerradas_no_ocupan_dosis(app, base, campana):
    entrada(app, base, 1)
    for numero, estado in enumerate(["cancelada", "no_asistio", "no_aplicada", "aplicada"]):
        reservar(app, base, campana, "2026-11-14", numero, estado)
    assert disponible(app, base, "2026-11-14")


def test_rf25_lote_sirve_el_dia_de_su_vencimiento(app, base):
    lote = crear_lote(app, base["vacuna"], codigo="CORTO", fecha_vencimiento="2026-11-14")
    entrada(app, base, 1, lote=lote)
    with app.app_context():
        # El lote base (vence 2026-11-30) no tiene existencias en este punto.
        assert hay_dosis(base["punto"], base["vacuna"], "2026-11-14")
        assert not hay_dosis(base["punto"], base["vacuna"], "2026-11-15")


def test_rf25_lote_vencido_no_cuenta(app, base, reloj):
    lote = crear_lote(app, base["vacuna"], codigo="VIEJO", fecha_vencimiento="2026-10-20")
    entrada(app, base, 5, lote=lote)
    assert disponible(app, base, "2026-10-15")
    reloj["ahora"] = reloj["ahora"].replace(day=21)  # 2026-10-21: ya venció
    assert not disponible(app, base, "2026-10-21")


def test_rf25_ejemplo_del_plan_lotes_10_y_20(app, base, campana):
    # Una dosis vence el 10 y otra el 20; hay una cita el 15.
    diez = crear_lote(app, base["vacuna"], codigo="VENCE-10", fecha_vencimiento="2026-11-10")
    veinte = crear_lote(app, base["vacuna"], codigo="VENCE-20", fecha_vencimiento="2026-11-20")
    entrada(app, base, 1, lote=diez)
    entrada(app, base, 1, lote=veinte)
    reservar(app, base, campana, "2026-11-15", 1)
    assert disponible(app, base, "2026-11-09")
    assert not disponible(app, base, "2026-11-16")


def test_reprogramar_excluye_la_propia_cita(app, base, campana):
    entrada(app, base, 1)
    cita = reservar(app, base, campana, "2026-11-14", 1)
    assert not disponible(app, base, "2026-11-20")
    assert disponible(app, base, "2026-11-20", excluir=cita)


def test_rf26_faltante_bloquea_nuevas_reservas_y_conserva_citas(app, base, campana):
    inventario_id = entrada(app, base, 2)
    reservar(app, base, campana, "2026-11-14", 1)
    reservar(app, base, campana, "2026-11-14", 2)
    with app.app_context():
        Inventario.buscar(inventario_id).ajustar("-1", "Dosis dañada", base["admin"])
        assert dosis_sin_cubrir(base["punto"], base["vacuna"]) == 1
        activas = get_db().execute(
            "SELECT COUNT(*) FROM citas WHERE estado = 'reservada'").fetchone()[0]
    assert activas == 2
    assert not disponible(app, base, "2026-11-14")


def test_rf26_resumen_muestra_el_faltante(app, base, campana):
    inventario_id = entrada(app, base, 1)
    reservar(app, base, campana, "2026-11-14", 1)
    with app.app_context():
        Inventario.buscar(inventario_id).ajustar("-1", "Dosis dañada", base["admin"])
        fila = Inventario.resumen()[0]
    assert (fila["utilizables"], fila["reservadas"], fila["faltante"]) == (0, 1, 1)


def cubrible_por_conteo(lotes, fechas, hoy):
    """Regla independiente (Hall): para cada fecha t, las reservas que necesitan
    un lote que dure hasta t o más no pueden superar las unidades que duran tanto."""
    for t in sorted(set(max(f, hoy) for f in fechas)):
        necesitan = sum(1 for f in fechas if max(f, hoy) >= t)
        alcanzan = sum(cantidad for vence, cantidad in lotes if vence >= t)
        if necesitan > alcanzan:
            return False
    return True


def test_asignacion_coincide_con_la_regla_de_conteo_en_casos_pequenos(app, base, campana):
    """Compara la asignación por vencimiento con la regla de conteo en 40 casos aleatorios."""
    dias = ["2026-10-10", "2026-10-15", "2026-10-20", "2026-10-25"]
    azar = random.Random(7)
    contador = itertools.count()
    # Cada paciente tiene una sola cita activa por vacuna: un grupo fijo alcanza.
    pacientes = [crear_paciente(app, identificacion=f"G{n}", correo=f"g{n}@example.com")
                 for n in range(4)]
    for caso in range(40):
        with app.app_context():
            db = get_db()
            db.execute("DELETE FROM citas")
            db.execute("DELETE FROM movimientos_inventario")
            db.execute("DELETE FROM inventarios_biologicos")
            db.commit()
        lotes = []
        for _ in range(azar.randint(0, 3)):
            vence, cantidad = azar.choice(dias), azar.randint(1, 2)
            lote = crear_lote(app, base["vacuna"], codigo=f"C{next(contador)}", fecha_vencimiento=vence)
            entrada(app, base, cantidad, lote=lote)
            lotes.append((vence, cantidad))
        fechas = [azar.choice(dias) for _ in range(azar.randint(0, 4))]
        for paciente, fecha in zip(pacientes, fechas):
            reservar(app, base, campana, fecha, 0, usuario_id=paciente)
        nueva = azar.choice(dias)
        esperado = cubrible_por_conteo(lotes, fechas + [nueva], "2026-10-08")
        assert disponible(app, base, nueva) == esperado, (caso, lotes, fechas, nueva)
