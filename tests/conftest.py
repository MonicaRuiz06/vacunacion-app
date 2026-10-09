"""Configuración común de pruebas: cada prueba usa una base temporal."""

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "prueba.db"),
        "WTF_CSRF_ENABLED": False,
    })
    yield app


@pytest.fixture
def client(app):
    return app.test_client()
