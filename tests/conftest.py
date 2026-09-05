"""Fiecare test primeste o baza de date proaspata, in memorie."""

from __future__ import annotations

import json

import pytest

from gestio import db


@pytest.fixture(autouse=True)
def memory_db():
    conn = db.connect(":memory:")
    db.set_conn(conn)
    yield conn
    conn.close()
    db.set_conn(None)  # type: ignore[arg-type]


@pytest.fixture
def call():
    """Apeleaza o unealta si intoarce raspunsul deserializat."""

    def _call(tool, **kwargs):
        return json.loads(tool(**kwargs))

    return _call


@pytest.fixture
def ok(call):
    """La fel ca `call`, dar esueaza testul daca unealta a raportat o eroare."""

    def _ok(tool, **kwargs):
        result = call(tool, **kwargs)
        assert "eroare" not in result, f"{tool.name} a esuat: {result.get('eroare')}"
        return result

    return _ok
