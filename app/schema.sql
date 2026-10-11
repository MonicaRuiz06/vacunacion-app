-- Esquema relacional del Sistema de Gestión de Campañas de Vacunación.
-- Motor: SQLite (requisito). Se usa el módulo sqlite3
-- de la biblioteca estándar de Python para ejecutar este script; no
-- se usa ningún ORM.
--

PRAGMA foreign_keys = ON;

-- Cuentas de acceso de los tres roles (M02). La identidad (nombre,
-- documento y correo) vive aquí para no repetirla en pacientes.
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo TEXT NOT NULL,
    tipo_documento TEXT NOT NULL CHECK (tipo_documento IN ('CC', 'CE', 'PASAPORTE')),
    identificacion TEXT NOT NULL,     -- texto en mayúsculas: conserva ceros iniciales
    correo TEXT NOT NULL UNIQUE,      -- guardado en minúsculas
    password_hash TEXT,               -- NULL mientras la invitación está pendiente
    rol TEXT NOT NULL CHECK (rol IN ('administrador', 'vacunador', 'paciente')),
    activo INTEGER NOT NULL DEFAULT 1,
    version_credenciales INTEGER NOT NULL DEFAULT 0,  -- al subir, cierra todas las sesiones
    creado_en TEXT NOT NULL,
    UNIQUE (tipo_documento, identificacion)
);

-- Datos propios del paciente. Nombre, documento y correo pasaron a
-- usuarios (M02); el resto de columnas se conserva.
CREATE TABLE IF NOT EXISTS pacientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL UNIQUE REFERENCES usuarios(id),
    fecha_nacimiento TEXT NOT NULL,   -- formato ISO 'YYYY-MM-DD'
    genero TEXT,
    telefono TEXT,
    direccion TEXT,
    municipio TEXT,
    declaracion_responsable TEXT      -- fecha en que declaró autorización (16 o 17 años)
);

-- La vacuna es el producto; sus lotes van en la tabla lotes (M04).
CREATE TABLE IF NOT EXISTS vacunas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    fabricante TEXT,
    dosis_requeridas INTEGER NOT NULL DEFAULT 1 CHECK (dosis_requeridas >= 1)
);

-- Lotes de cada vacuna (M04). Un lote sirve hasta su fecha de vencimiento,
-- inclusive; el mismo código puede repetirse en vacunas distintas.
CREATE TABLE IF NOT EXISTS lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacuna_id INTEGER NOT NULL REFERENCES vacunas(id),
    codigo TEXT NOT NULL,
    fecha_vencimiento TEXT NOT NULL,  -- formato ISO 'YYYY-MM-DD'
    UNIQUE (vacuna_id, codigo)
);

CREATE TABLE IF NOT EXISTS puntos_vacunacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    direccion TEXT NOT NULL,
    municipio TEXT,
    hora_apertura TEXT NOT NULL,      -- formato 'HH:MM'
    hora_cierre TEXT NOT NULL,        -- formato 'HH:MM'
    capacidad_diaria INTEGER NOT NULL DEFAULT 50
);

-- Campañas (M04): nacen en borrador y se publican a mano.
CREATE TABLE IF NOT EXISTS campanas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    fecha_inicio TEXT NOT NULL,       -- formato ISO 'YYYY-MM-DD'
    fecha_fin TEXT NOT NULL,          -- formato ISO 'YYYY-MM-DD'
    estado TEXT NOT NULL DEFAULT 'borrador'
        CHECK (estado IN ('borrador', 'publicada', 'pausada', 'finalizada'))
);

-- Puntos y vacunas que participan en cada campaña (M04).
CREATE TABLE IF NOT EXISTS campana_puntos (
    campana_id INTEGER NOT NULL REFERENCES campanas(id),
    punto_id INTEGER NOT NULL REFERENCES puntos_vacunacion(id),
    PRIMARY KEY (campana_id, punto_id)
);

CREATE TABLE IF NOT EXISTS campana_vacunas (
    campana_id INTEGER NOT NULL REFERENCES campanas(id),
    vacuna_id INTEGER NOT NULL REFERENCES vacunas(id),
    PRIMARY KEY (campana_id, vacuna_id)
);

-- Franjas de atención por punto y fecha (M04). Sus cupos se comparten
-- entre todas las campañas del punto.
CREATE TABLE IF NOT EXISTS franjas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    punto_id INTEGER NOT NULL REFERENCES puntos_vacunacion(id),
    fecha TEXT NOT NULL,              -- formato ISO 'YYYY-MM-DD'
    hora_inicio TEXT NOT NULL,        -- formato 'HH:MM'
    hora_fin TEXT NOT NULL,           -- formato 'HH:MM'
    cupos INTEGER NOT NULL CHECK (cupos >= 1)
);

-- Existencias físicas por punto y lote (M05). La vacuna se obtiene del
-- lote. El saldo nunca es negativo y no se borra en cascada: cada cambio
-- queda en movimientos_inventario.
CREATE TABLE IF NOT EXISTS inventarios_biologicos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    punto_id INTEGER NOT NULL REFERENCES puntos_vacunacion(id),
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    cantidad_disponible INTEGER NOT NULL DEFAULT 0 CHECK (cantidad_disponible >= 0),
    UNIQUE (punto_id, lote_id)
);

-- Historial de cada cambio de saldo (M05): quién, cuánto, por qué y cuándo.
-- clave evita registrar dos veces el mismo formulario enviado de nuevo.
CREATE TABLE IF NOT EXISTS movimientos_inventario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventario_id INTEGER NOT NULL REFERENCES inventarios_biologicos(id),
    cantidad INTEGER NOT NULL CHECK (cantidad != 0),  -- positiva entra, negativa sale
    tipo TEXT NOT NULL
        CHECK (tipo IN ('entrada', 'ajuste', 'aplicacion', 'correccion', 'anulacion')),
    motivo TEXT NOT NULL,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    fecha TEXT NOT NULL,
    clave TEXT UNIQUE
);

-- Citas (formato nuevo desde M04). Punto, fecha y hora salen de la franja.
-- Reservada y presente ocupan cupo y reservan una dosis; aplicada,
-- no aplicada y registro anulado siguen ocupando cupo; cancelada y no
-- asistió lo liberan (RF-41). Sin borrado en cascada: la historia se conserva.
CREATE TABLE IF NOT EXISTS citas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    campana_id INTEGER NOT NULL REFERENCES campanas(id),
    vacuna_id INTEGER NOT NULL REFERENCES vacunas(id),
    franja_id INTEGER NOT NULL REFERENCES franjas(id),
    estado TEXT NOT NULL DEFAULT 'reservada'
        CHECK (estado IN ('reservada', 'presente', 'aplicada', 'no_aplicada',
                          'registro_anulado', 'cancelada', 'no_asistio')),
    creado_en TEXT NOT NULL,
    llegada_en TEXT,
    llegada_por INTEGER REFERENCES usuarios(id),
    cierre_en TEXT,
    motivo TEXT
);

-- Dosis aplicadas (formato nuevo desde M09). Cada aplicación se enlaza a su
-- cita, al lote real y a quien la registró. Una anulación no borra la fila:
-- la marca como anulada. rectifica_id apunta a la aplicación errónea que
-- esta reemplaza (RF-42). Sin borrado en cascada: la historia se conserva.
CREATE TABLE IF NOT EXISTS dosis_aplicadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id INTEGER NOT NULL REFERENCES citas(id),
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    vacuna_id INTEGER NOT NULL REFERENCES vacunas(id),
    punto_id INTEGER NOT NULL REFERENCES puntos_vacunacion(id),
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    numero_dosis INTEGER NOT NULL CHECK (numero_dosis >= 1),
    fecha_aplicacion TEXT NOT NULL,   -- formato ISO 'YYYY-MM-DD' (fecha real)
    registrado_en TEXT NOT NULL,
    registrado_por INTEGER NOT NULL REFERENCES usuarios(id),
    estado TEXT NOT NULL DEFAULT 'vigente' CHECK (estado IN ('vigente', 'anulada')),
    rectifica_id INTEGER REFERENCES dosis_aplicadas(id)
);

-- Enlaces de recuperación e invitación (M02): se guarda solo el hash,
-- vencen a los 30 minutos y se borran al usarse o al pedir uno nuevo.
CREATE TABLE IF NOT EXISTS tokens_cuenta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    proposito TEXT NOT NULL CHECK (proposito IN ('recuperacion', 'invitacion')),
    token_hash TEXT NOT NULL UNIQUE,
    expira_en TEXT NOT NULL
);

-- Puntos donde puede trabajar cada vacunador (M02).
CREATE TABLE IF NOT EXISTS vacunador_punto (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    punto_id INTEGER NOT NULL REFERENCES puntos_vacunacion(id),
    PRIMARY KEY (usuario_id, punto_id)
);

-- Avisos internos (M06): se guardan junto con el cambio que los produce
-- (por ejemplo, una cancelación) y el correo se intenta después. Si el
-- correo falla, el aviso se conserva y el personal puede reintentar.
CREATE TABLE IF NOT EXISTS notificaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    cita_id INTEGER REFERENCES citas(id),
    asunto TEXT NOT NULL,
    mensaje TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    leido_en TEXT,
    correo_estado TEXT NOT NULL DEFAULT 'pendiente'
        CHECK (correo_estado IN ('pendiente', 'enviado', 'fallido')),
    correo_intentos INTEGER NOT NULL DEFAULT 0
);

-- Historial de cambios importantes (quién, qué y cuándo). Nunca guarda
-- contraseñas ni enlaces.
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER NOT NULL REFERENCES usuarios(id),
    accion TEXT NOT NULL,
    tabla TEXT NOT NULL,
    registro_id INTEGER NOT NULL,
    detalle TEXT,                     -- valores anteriores y nuevos en JSON
    motivo TEXT,
    fecha TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_citas_franja ON citas (franja_id);
-- Un paciente solo puede tener una cita activa por vacuna (RF-16).
CREATE UNIQUE INDEX IF NOT EXISTS idx_una_cita_activa ON citas (paciente_id, vacuna_id)
    WHERE estado IN ('reservada', 'presente');
CREATE INDEX IF NOT EXISTS idx_franjas_punto_fecha ON franjas (punto_id, fecha);
CREATE INDEX IF NOT EXISTS idx_dosis_paciente ON dosis_aplicadas (paciente_id);
-- Una aplicación vigente por cita y por paciente, vacuna y número (RF-28, RF-29).
CREATE UNIQUE INDEX IF NOT EXISTS idx_una_dosis_por_cita ON dosis_aplicadas (cita_id)
    WHERE estado = 'vigente';
CREATE UNIQUE INDEX IF NOT EXISTS idx_una_dosis_por_numero
    ON dosis_aplicadas (paciente_id, vacuna_id, numero_dosis) WHERE estado = 'vigente';
