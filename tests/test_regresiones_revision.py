from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from tests.conftest import atender, aplicar, crear_paciente
from app.db import get_db
from app.models.punto import Punto
from app.models.dosis import DosisAplicada
from app.models.usuario import Usuario, crear_token, usar_token


def test_reducir_capacidad_diaria_bajo_ocupacion_se_rechaza(app, esc, reloj):
    otro = crear_paciente(app, identificacion='2002', correo='otro@example.test')
    atender(app, esc, reloj, esc['paciente'])
    atender(app, esc, reloj, otro)
    with app.app_context():
        punto = Punto.buscar(esc['campus'])
        punto.capacidad_diaria = 1
        with pytest.raises(ValueError):
            punto.guardar()
        assert Punto.buscar(punto.id).capacidad_diaria != 1
        punto.capacidad_diaria = 2
        punto.guardar()
        assert Punto.buscar(punto.id).capacidad_diaria == 2


def test_rectificacion_mismo_lote_agotado_no_necesita_otra_unidad(app, esc, reloj):
    otro = crear_paciente(app, identificacion='2002', correo='otro@example.test')
    origen = atender(app, esc, reloj, esc['paciente'])
    destino = atender(app, esc, reloj, otro)
    with app.app_context():
        # Simula el saldo disponible antes de registrar la última dosis física.
        db = get_db()
        db.execute('UPDATE inventarios_biologicos SET cantidad_disponible=1 WHERE punto_id=?', (esc['campus'],))
        db.commit()
    dosis_id = aplicar(app, esc, origen)
    with app.app_context():
        opciones = DosisAplicada.lotes_del_punto(esc['campus'], '2026-10-20', esc['lote'])
        assert esc['lote'] in [fila['id'] for fila in opciones]
        movimientos = get_db().execute('SELECT COUNT(*) FROM movimientos_inventario').fetchone()[0]
        nueva = DosisAplicada.buscar(dosis_id).rectificar(Usuario.buscar(esc['admin']), destino, esc['lote'], 1, 'Corregir paciente')
        assert nueva
        assert get_db().execute('SELECT COUNT(*) FROM movimientos_inventario').fetchone()[0] == movimientos
        assert get_db().execute('SELECT cantidad_disponible FROM inventarios_biologicos WHERE punto_id=?', (esc['campus'],)).fetchone()[0] == 0


def test_token_solo_un_consumo_concurrente(app, esc, monkeypatch):
    import app.models.usuario as modulo
    with app.app_context():
        token = crear_token(esc['paciente'], 'recuperacion')
        get_db().commit()
    primero_listo, segundo_intenta = Event(), Event()
    generar = modulo.generate_password_hash
    def generar_coordinado(valor):
        if valor == 'Nueva#123A':
            primero_listo.set()
            assert segundo_intenta.wait(5)
        else:
            segundo_intenta.set()
        return generar(valor)
    monkeypatch.setattr(modulo, 'generate_password_hash', generar_coordinado)
    def consumir(clave):
        with app.app_context():
            if clave == 'Nueva#123B':
                get_db().set_trace_callback(
                    lambda sql: segundo_intenta.set() if sql == 'BEGIN IMMEDIATE' else None)
            try:
                usar_token(token, 'recuperacion', clave)
                return 'aceptado'
            except ValueError:
                return 'rechazado'
    with ThreadPoolExecutor(max_workers=2) as pool:
        primero = pool.submit(consumir, 'Nueva#123A')
        assert primero_listo.wait(5)
        segundo = pool.submit(consumir, 'Nueva#123B')
        resultados = [primero.result(), segundo.result()]
    assert resultados.count('aceptado') == 1, resultados


def test_inventario_libera_reservas_vencidas_antes_de_mostrar(app, client, esc, reloj):
    from tests.conftest import ingresar, hora
    from app.models.cita import Cita
    with app.app_context():
        cita_id = Cita.reservar(Usuario.buscar(esc['paciente']), esc['campana'], esc['vacuna'], esc['franja'])
    reloj['ahora'] = hora('2026-10-20 10:00')
    ingresar(client, identificacion='9001')
    assert client.get('/inventario').status_code == 200
    with app.app_context():
        assert Cita.buscar(cita_id).estado == 'no_asistio'
