"""Conexión e inicialización de SQLite para Flask (sin ORM)."""

import os
import sqlite3

import click
from flask import current_app, g


def get_db():
    """Devuelve la conexión de la petición actual, creándola si hace falta."""
    if "db" not in g:
        database_path = current_app.config["DATABASE"]
        os.makedirs(os.path.dirname(os.path.abspath(database_path)), exist_ok=True)
        g.db = sqlite3.connect(database_path)
        g.db.row_factory = sqlite3.Row
        # SQLite requiere activarlas en cada conexión; el PRAGMA del schema.sql
        # solo afecta a la conexión que ejecuta ese script.
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Crea las tablas e índices definidos en app/schema.sql si faltan."""
    db = get_db()
    with current_app.open_resource("schema.sql") as schema_file:
        db.executescript(schema_file.read().decode("utf-8"))


@click.command("init-db")
def init_db_command():
    """Inicializa la base usando el esquema del proyecto."""
    init_db()
    click.echo("Base de datos inicializada.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
