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

CREATE TABLE IF NOT EXISTS vacunas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    fabricante TEXT,
    lote TEXT NOT NULL,
    fecha_vencimiento TEXT NOT NULL,  -- formato ISO 'YYYY-MM-DD'
    dosis_requeridas INTEGER NOT NULL DEFAULT 1
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

-- El inventario es solo un conteo de existencias por punto+vacuna:
-- si se borra el punto o la vacuna, el conteo pierde sentido, por
-- eso aquí SÍ hay ON DELETE CASCADE en ambas llaves foráneas.
CREATE TABLE IF NOT EXISTS inventarios_biologicos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    punto_id INTEGER NOT NULL REFERENCES puntos_vacunacion(id) ON DELETE CASCADE,
    vacuna_id INTEGER NOT NULL REFERENCES vacunas(id) ON DELETE CASCADE,
    cantidad_disponible INTEGER NOT NULL DEFAULT 0,
    UNIQUE (punto_id, vacuna_id)
);

-- paciente_id sí elimina en cascada (la cita le pertenece al paciente).
-- vacuna_id y punto_id NO tienen ON DELETE: si tienen citas asociadas,
-- SQLite rechaza el DELETE con un error de integridad (el controlador
-- lo debe capturar y avisar al usuario, no dejar borrar en silencio).
CREATE TABLE IF NOT EXISTS citas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
    vacuna_id INTEGER NOT NULL REFERENCES vacunas(id),
    punto_id INTEGER NOT NULL REFERENCES puntos_vacunacion(id),
    fecha TEXT NOT NULL,              -- formato ISO 'YYYY-MM-DD'
    hora TEXT NOT NULL,               -- formato 'HH:MM'
    estado TEXT NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'confirmada', 'atendida', 'cancelada'))
);

-- Misma lógica que citas: paciente_id en cascada, vacuna_id y
-- punto_id restringidos (protegen el historial real de aplicación).
CREATE TABLE IF NOT EXISTS dosis_aplicadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
    vacuna_id INTEGER NOT NULL REFERENCES vacunas(id),
    punto_id INTEGER NOT NULL REFERENCES puntos_vacunacion(id),
    numero_dosis INTEGER NOT NULL DEFAULT 1,
    fecha_aplicacion TEXT NOT NULL,   -- formato ISO 'YYYY-MM-DD'
    lote_aplicado TEXT
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

CREATE INDEX IF NOT EXISTS idx_citas_punto_fecha_hora ON citas (punto_id, fecha, hora);
CREATE INDEX IF NOT EXISTS idx_dosis_paciente ON dosis_aplicadas (paciente_id);
