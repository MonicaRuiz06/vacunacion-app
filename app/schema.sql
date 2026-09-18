-- Esquema relacional del Sistema de Gestión de Campañas de Vacunación.
-- Motor: SQLite (requisito). Se usa el módulo sqlite3
-- de la biblioteca estándar de Python para ejecutar este script; no
-- se usa ningún ORM.
--

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pacientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo TEXT NOT NULL,
    identificacion TEXT NOT NULL UNIQUE,
    fecha_nacimiento TEXT NOT NULL,   -- formato ISO 'YYYY-MM-DD'
    genero TEXT,
    telefono TEXT,
    correo TEXT,
    direccion TEXT,
    municipio TEXT
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

CREATE INDEX IF NOT EXISTS idx_citas_punto_fecha_hora ON citas (punto_id, fecha, hora);
CREATE INDEX IF NOT EXISTS idx_dosis_paciente ON dosis_aplicadas (paciente_id);
