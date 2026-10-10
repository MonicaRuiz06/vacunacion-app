"""Pruebas del modelo de citas (M07): RF-04, RF-14–22, RF-36, RF-38, RF-41, RNF-06."""

import threading

import pytest

from app.db import get_db
from app.models.campana import Campana
from app.models.cita import Cita
from app.models.franja import Franja
from app.models.inventario import hay_dosis, registrar_entrada
from app.models.paciente import Paciente
from app.models.usuario import Usuario
from app.utils import ErroresFormulario
from tests.conftest import (
    FRANJA_FECHA,
    crear_campana,
    crear_franja,
    crear_lote,
    crear_paciente,
    crear_punto,
    crear_vacuna,
    hora,
)

def usuario(app, usuario_id):
    with app.app_context():
        return Usuario.buscar(usuario_id)


def reservar(app, esc, usuario_id=None, franja=None, vacuna=None, campana=None):
    with app.app_context():
        return Cita.reservar(Usuario.buscar(usuario_id or esc["paciente"]), campana or esc["campana"],
                             vacuna or esc["vacuna"], franja or esc["franja"])


def otro_paciente(app, numero):
    return crear_paciente(app, identificacion=f"20{numero}", correo=f"otro{numero}@example.com")


def cita(app, cita_id):
    with app.app_context():
        return Cita.buscar(cita_id)


def ocupados(app, franja_id):
    with app.app_context():
        return Franja.buscar(franja_id).ocupados()


# RF-14 — Reserva


def test_rf14_reserva_ocupa_cupo_y_aparta_dosis(app, esc):
    cita_id = reservar(app, esc)
    assert cita(app, cita_id).estado == "reservada"
    assert ocupados(app, esc["franja"]) == 1
    with app.app_context():
        # 10 dosis en Campus: con 9 reservas más todavía alcanza, con 10 ya no.
        from app.models.inventario import dosis_sin_cubrir
        assert dosis_sin_cubrir(esc["campus"], esc["vacuna"], [FRANJA_FECHA] * 9) == 0
        assert dosis_sin_cubrir(esc["campus"], esc["vacuna"], [FRANJA_FECHA] * 10) == 1


def test_rf04_cuenta_nueva_reserva_sin_verificar_correo(app, esc):
    nuevo = crear_paciente(app, identificacion="3001", correo="nuevo@example.com")
    assert cita(app, reservar(app, esc, usuario_id=nuevo)).estado == "reservada"


@pytest.mark.parametrize("accion", ["pausar", "borrador"])
def test_rf10_campana_sin_reservas(app, esc, accion):
    with app.app_context():
        if accion == "pausar":
            Campana.buscar(esc["campana"]).pausar(esc["admin"])
            campana_id = esc["campana"]
        else:
            campana_id = crear_campana(app, esc["admin"], puntos=[esc["campus"]], vacunas=[esc["vacuna"]],
                                       nombre="Borrador", fecha_inicio="2026-10-10", fecha_fin="2026-11-30")
    with pytest.raises(ValueError):
        reservar(app, esc, campana=campana_id)


def test_rf14_vacuna_o_franja_fuera_de_la_campana(app, esc):
    otra_vacuna = crear_vacuna(app, nombre="Tétanos")
    otro_punto = crear_punto(app, "Punto Norte")
    franja_norte = crear_franja(app, otro_punto, fecha=FRANJA_FECHA)
    franja_fuera = crear_franja(app, esc["campus"], fecha="2026-12-15")
    for cambios in ({"vacuna": otra_vacuna}, {"franja": franja_norte}, {"franja": franja_fuera}):
        with pytest.raises(ValueError):
            reservar(app, esc, **cambios)


def test_rf11_franja_llena_aun_entre_campanas(app, esc):
    otra_campana = crear_campana(app, esc["admin"], puntos=[esc["campus"]], vacunas=[esc["vacuna"]],
                                 nombre="Otra", fecha_inicio="2026-10-10", fecha_fin="2026-11-30")
    with app.app_context():
        Campana.buscar(otra_campana).publicar(esc["admin"])
    reservar(app, esc)
    reservar(app, esc, usuario_id=otro_paciente(app, 1), campana=otra_campana)
    with pytest.raises(ValueError, match="cupos"):
        reservar(app, esc, usuario_id=otro_paciente(app, 2))


def test_rf11_capacidad_diaria_del_punto(app, esc):
    with app.app_context():
        get_db().execute("UPDATE puntos_vacunacion SET capacidad_diaria = 1 WHERE id = ?", (esc["campus"],))
        get_db().commit()
    reservar(app, esc)
    with pytest.raises(ValueError, match="capacidad"):
        reservar(app, esc, usuario_id=otro_paciente(app, 1), franja=esc["otra_franja"])


def test_rf14_sin_dosis_no_reserva(app, esc):
    sin_lotes = crear_vacuna(app, nombre="Hepatitis B")
    with app.app_context():
        campana = Campana.buscar(esc["campana"])
        campana.vacunas_ids = [esc["vacuna"], sin_lotes]
        campana.guardar(esc["admin"])
    with pytest.raises(ValueError, match="dosis"):
        reservar(app, esc, vacuna=sin_lotes)


# RF-15 — Dos horas antes


def test_rf15_reserva_exactamente_dos_horas_antes(app, esc, reloj):
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 07:00")
    reservar(app, esc)


def test_rf15_reserva_un_segundo_despues_se_rechaza(app, esc, reloj):
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 07:00:01")
    with pytest.raises(ValueError, match="2 horas"):
        reservar(app, esc)


# RF-16 — Una cita activa por vacuna


def test_rf16_una_cita_activa_por_vacuna(app, esc):
    cita_id = reservar(app, esc)
    with pytest.raises(ValueError, match="activa"):
        reservar(app, esc, franja=esc["franja_centro"])
    with app.app_context():
        Cita.buscar(cita_id).cancelar(Usuario.buscar(esc["paciente"]))
    reservar(app, esc, franja=esc["franja_centro"])


def test_rf16_esquema_completo_bloquea(app, esc):
    with app.app_context():
        db = get_db()
        paciente_id = Paciente.buscar_por_usuario(esc["paciente"]).id
        db.execute("INSERT INTO dosis_aplicadas (paciente_id, vacuna_id, punto_id, numero_dosis,"
                   " fecha_aplicacion) VALUES (?, ?, ?, 1, '2026-09-01')",
                   (paciente_id, esc["vacuna"], esc["campus"]))
        db.commit()
    with pytest.raises(ValueError, match="todas las dosis"):
        reservar(app, esc)


# RF-17 — Cancelación por el paciente


def test_rf17_paciente_cancela_y_libera(app, esc):
    cita_id = reservar(app, esc)
    with app.app_context():
        Cita.buscar(cita_id).cancelar(Usuario.buscar(esc["paciente"]))
        assert hay_dosis(esc["campus"], esc["vacuna"], FRANJA_FECHA)
    assert cita(app, cita_id).estado == "cancelada"
    assert ocupados(app, esc["franja"]) == 0


def test_rf17_paciente_no_cancela_fuera_de_plazo(app, esc, reloj):
    cita_id = reservar(app, esc)
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 07:30")
    with app.app_context():
        with pytest.raises(ValueError):
            Cita.buscar(cita_id).cancelar(Usuario.buscar(esc["paciente"]))


def test_rf17_paciente_no_cancela_cita_ajena(app, esc):
    cita_id = reservar(app, esc)
    ajeno = otro_paciente(app, 1)
    with app.app_context():
        with pytest.raises(PermissionError):
            Cita.buscar(cita_id).cancelar(Usuario.buscar(ajeno))


# RF-18 — Reprogramación por el paciente


def test_rf18_reprograma_y_mueve_el_cupo(app, esc):
    cita_id = reservar(app, esc)
    with app.app_context():
        Cita.buscar(cita_id).reprogramar(Usuario.buscar(esc["paciente"]), esc["campana"],
                                         esc["vacuna"], esc["otra_franja"])
    assert cita(app, cita_id).franja_id == esc["otra_franja"]
    assert ocupados(app, esc["franja"]) == 0
    assert ocupados(app, esc["otra_franja"]) == 1


def test_rf18_destino_lleno_conserva_la_original(app, esc):
    cita_id = reservar(app, esc)
    for numero in range(2):
        reservar(app, esc, usuario_id=otro_paciente(app, numero), franja=esc["otra_franja"])
    with app.app_context():
        with pytest.raises(ValueError):
            Cita.buscar(cita_id).reprogramar(Usuario.buscar(esc["paciente"]), esc["campana"],
                                             esc["vacuna"], esc["otra_franja"])
    original = cita(app, cita_id)
    assert (original.estado, original.franja_id) == ("reservada", esc["franja"])


def test_rf18_misma_franja_no_cuenta_dos_veces_su_cupo(app, esc):
    cita_id = reservar(app, esc)
    reservar(app, esc, usuario_id=otro_paciente(app, 1))  # la franja queda llena
    with app.app_context():
        Cita.buscar(cita_id).reprogramar(Usuario.buscar(esc["paciente"]), esc["campana"],
                                         esc["vacuna"], esc["franja"])


def test_rf18_plazo_doble_origen_y_destino(app, esc, reloj):
    temprana = crear_franja(app, esc["campus"], fecha="2026-10-21", hora_inicio="08:00", hora_fin="08:30")
    cita_id = reservar(app, esc, franja=temprana)
    reloj["ahora"] = hora("2026-10-21 06:30")  # faltan 1 h 30 min para la original
    with app.app_context():
        with pytest.raises(ValueError, match="2 horas"):
            Cita.buscar(cita_id).reprogramar(Usuario.buscar(esc["paciente"]), esc["campana"],
                                             esc["vacuna"], esc["franja"])
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 07:30")  # destino a 1 h 30 min
    otra = reservar(app, esc, usuario_id=otro_paciente(app, 1), franja=temprana)
    with app.app_context():
        with pytest.raises(ValueError, match="2 horas"):
            Cita.buscar(otra).reprogramar(Usuario.buscar(otro_paciente_id(app, 1)), esc["campana"],
                                          esc["vacuna"], esc["franja"])


def otro_paciente_id(app, numero):
    with app.app_context():
        return Usuario.buscar_por_documento("CC", f"20{numero}").id


def test_rf18_cambia_de_vacuna(app, esc):
    tetanos = crear_vacuna(app, nombre="Tétanos")
    lote = crear_lote(app, tetanos, codigo="TT-1", fecha_vencimiento="2026-12-31")
    with app.app_context():
        registrar_entrada(esc["campus"], lote, 5, "Entrega", esc["admin"])
        campana = Campana.buscar(esc["campana"])
        campana.vacunas_ids = [esc["vacuna"], tetanos]
        campana.guardar(esc["admin"])
    cita_id = reservar(app, esc)
    with app.app_context():
        Cita.buscar(cita_id).reprogramar(Usuario.buscar(esc["paciente"]), esc["campana"],
                                         tetanos, esc["franja"])
    assert cita(app, cita_id).vacuna_id == tetanos


# RF-19 / RF-20 — Llegada e inasistencia


def llegar(app, cita_id, usuario_id):
    with app.app_context():
        Cita.buscar(cita_id).registrar_llegada(Usuario.buscar(usuario_id))


def test_rf19_llegada_desde_el_inicio_exacto(app, esc, reloj):
    cita_id = reservar(app, esc)
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 08:59:59")
    with pytest.raises(ValueError):
        llegar(app, cita_id, esc["vacunador"])
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:00")
    llegar(app, cita_id, esc["vacunador"])
    actual = cita(app, cita_id)
    assert actual.estado == "presente"
    assert actual.llegada_por == esc["vacunador"]


def test_rf19_rf20_en_el_umbral_no_hay_llegada_y_queda_no_asistio(app, esc, reloj):
    cita_id = reservar(app, esc)
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 10:00")  # fin 09:30 + 30 min
    with pytest.raises(ValueError):
        llegar(app, cita_id, esc["admin"])
    assert cita(app, cita_id).estado == "no_asistio"


def test_rf19_vacunador_de_otro_punto_no_registra_llegada(app, esc, reloj):
    cita_id = reservar(app, esc, franja=esc["franja_centro"])
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:10")
    with pytest.raises(PermissionError):
        llegar(app, cita_id, esc["vacunador"])
    llegar(app, cita_id, esc["admin"])


def test_rf20_vencidas_se_procesan_y_presente_queda_protegida(app, esc, reloj):
    ausente = reservar(app, esc)
    presente = reservar(app, esc, usuario_id=otro_paciente(app, 1))
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:15")
    llegar(app, presente, esc["vacunador"])
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:59:59")
    with app.app_context():
        Cita.procesar_vencidas()
    assert cita(app, ausente).estado == "reservada"
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 10:00")
    with app.app_context():
        Cita.procesar_vencidas()
        Cita.procesar_vencidas()  # repetir no cambia nada
    assert cita(app, ausente).estado == "no_asistio"
    assert cita(app, presente).estado == "presente"
    assert ocupados(app, esc["franja"]) == 1  # la inasistencia libera su cupo


def test_rf20_al_arrancar_se_procesan_las_vencidas(app, esc):
    from app import create_app

    cita_id = reservar(app, esc)
    with app.app_context():
        # Una franja ya pasada según el reloj real del sistema.
        get_db().execute("UPDATE franjas SET fecha = '2020-01-01' WHERE id = ?", (esc["franja"],))
        get_db().commit()
    create_app({"TESTING": True, "DATABASE": app.config["DATABASE"]})
    assert cita(app, cita_id).estado == "no_asistio"


# RF-21 / RF-22 / RF-36 — Personal


def test_rf21_personal_cancela_con_motivo_y_avisa(app, esc):
    cita_id = reservar(app, esc)
    with app.app_context():
        with pytest.raises(ErroresFormulario):
            Cita.buscar(cita_id).cancelar(Usuario.buscar(esc["vacunador"]), "")
        Cita.buscar(cita_id).cancelar(Usuario.buscar(esc["vacunador"]), "Punto cerrado por lluvia")
        aviso = get_db().execute("SELECT mensaje, correo_estado FROM notificaciones").fetchone()
    assert cita(app, cita_id).estado == "cancelada"
    assert "Punto cerrado por lluvia" in aviso["mensaje"]
    assert aviso["correo_estado"] == "enviado"
    assert "Punto cerrado por lluvia" in app.config["CORREOS_ENVIADOS"][-1]["texto"]


def test_rf21_personal_cancela_cita_con_llegada(app, esc, reloj):
    cita_id = reservar(app, esc)
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:10")
    llegar(app, cita_id, esc["vacunador"])
    with app.app_context():
        Cita.buscar(cita_id).cancelar(Usuario.buscar(esc["admin"]), "Contraindicación temporal")
    assert cita(app, cita_id).estado == "cancelada"


def test_rf21_vacunador_no_cancela_en_punto_ajeno(app, esc):
    cita_id = reservar(app, esc, franja=esc["franja_centro"])
    with app.app_context():
        with pytest.raises(PermissionError):
            Cita.buscar(cita_id).cancelar(Usuario.buscar(esc["vacunador"]), "Motivo")


@pytest.mark.parametrize("estado", ["aplicada", "no_aplicada", "cancelada", "no_asistio"])
def test_rf21_estados_cerrados_no_se_cancelan(app, esc, estado):
    cita_id = reservar(app, esc)
    with app.app_context():
        get_db().execute("UPDATE citas SET estado = ? WHERE id = ?", (estado, cita_id))
        get_db().commit()
        with pytest.raises(ValueError):
            Cita.buscar(cita_id).cancelar(Usuario.buscar(esc["admin"]), "Motivo")


def test_rf22_personal_reprograma_dentro_de_las_dos_horas(app, esc, reloj):
    cita_id = reservar(app, esc)
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 08:00")  # paciente ya no podría
    with app.app_context():
        Cita.buscar(cita_id).reprogramar(Usuario.buscar(esc["vacunador"]), esc["campana"],
                                         esc["vacuna"], esc["franja_centro"], "Traslado por demanda")
        aviso = get_db().execute("SELECT mensaje FROM notificaciones").fetchone()
    assert cita(app, cita_id).franja_id == esc["franja_centro"]  # destino en punto no asignado
    assert "Traslado por demanda" in aviso["mensaje"]


def test_rf22_destino_ya_iniciado_se_rechaza(app, esc, reloj):
    cita_id = reservar(app, esc, franja=esc["otra_franja"])
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:05")
    with app.app_context():
        with pytest.raises(ValueError, match="comenzó"):
            Cita.buscar(cita_id).reprogramar(Usuario.buscar(esc["admin"]), esc["campana"],
                                             esc["vacuna"], esc["franja"], "Motivo")


def test_rf22_vacunador_necesita_el_punto_de_origen(app, esc):
    cita_id = reservar(app, esc, franja=esc["franja_centro"])
    with app.app_context():
        with pytest.raises(PermissionError):
            Cita.buscar(cita_id).reprogramar(Usuario.buscar(esc["vacunador"]), esc["campana"],
                                             esc["vacuna"], esc["franja"], "Motivo")


def test_rf18_rf22_con_llegada_no_se_reprograma(app, esc, reloj):
    cita_id = reservar(app, esc)
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:10")
    llegar(app, cita_id, esc["vacunador"])
    with app.app_context():
        with pytest.raises(ValueError):
            Cita.buscar(cita_id).reprogramar(Usuario.buscar(esc["admin"]), esc["campana"],
                                             esc["vacuna"], esc["franja_centro"], "Motivo")


# RF-38 / RF-41 — Cierre sin aplicación


def test_rf38_no_aplicada_libera_dosis_y_conserva_cupo(app, esc, reloj):
    with app.app_context():
        get_db().execute("UPDATE inventarios_biologicos SET cantidad_disponible = 1 WHERE punto_id = ?",
                         (esc["campus"],))
        get_db().commit()
    cita_id = reservar(app, esc)
    with app.app_context():
        assert not hay_dosis(esc["campus"], esc["vacuna"], FRANJA_FECHA)
    reloj["ahora"] = hora(f"{FRANJA_FECHA} 09:10")
    llegar(app, cita_id, esc["vacunador"])
    with app.app_context():
        with pytest.raises(ErroresFormulario):
            Cita.buscar(cita_id).cerrar_sin_aplicar(Usuario.buscar(esc["vacunador"]), "")
        with pytest.raises(PermissionError):
            Cita.buscar(cita_id).cerrar_sin_aplicar(Usuario.buscar(esc["admin"]), "Fiebre")
        Cita.buscar(cita_id).cerrar_sin_aplicar(Usuario.buscar(esc["vacunador"]), "Fiebre al llegar")
        assert hay_dosis(esc["campus"], esc["vacuna"], FRANJA_FECHA)
    assert cita(app, cita_id).estado == "no_aplicada"
    assert ocupados(app, esc["franja"]) == 1


def test_rf38_solo_desde_presente(app, esc):
    cita_id = reservar(app, esc)
    with app.app_context():
        with pytest.raises(ValueError):
            Cita.buscar(cita_id).cerrar_sin_aplicar(Usuario.buscar(esc["vacunador"]), "Motivo")


# RNF-06 — Último cupo con dos conexiones


def test_rnf06_dos_pacientes_por_el_ultimo_cupo(app, esc):
    reservar(app, esc, usuario_id=otro_paciente(app, 9))  # queda un cupo
    pacientes = [otro_paciente(app, 1), otro_paciente(app, 2)]
    salida = threading.Barrier(2)
    resultados = []

    def intentar(usuario_id):
        with app.app_context():  # cada hilo abre su propia conexión al mismo archivo
            salida.wait()
            try:
                Cita.reservar(Usuario.buscar(usuario_id), esc["campana"], esc["vacuna"], esc["franja"])
                resultados.append("ok")
            except ValueError:
                resultados.append("rechazada")

    hilos = [threading.Thread(target=intentar, args=(p,)) for p in pacientes]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    assert sorted(resultados) == ["ok", "rechazada"]
    assert ocupados(app, esc["franja"]) == 2


def test_listados_por_rol(app, esc):
    reservar(app, esc)
    reservar(app, esc, usuario_id=otro_paciente(app, 1), franja=esc["franja_centro"])
    with app.app_context():
        assert len(Cita.de_paciente(esc["paciente"])) == 1
        assert len(Cita.agenda(Usuario.buscar(esc["admin"]))) == 2
        assert len(Cita.agenda(Usuario.buscar(esc["vacunador"]))) == 1  # solo Campus

