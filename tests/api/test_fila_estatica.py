import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.api.app import app  # noqa: E402

cliente = TestClient(app)


def test_a_pagina_da_fila_e_servida():
    r = cliente.get("/fila.html")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # Âncoras estruturais: o ponto de montagem que o JS escreve e o script
    # sem o qual a página não desenha nada. Existem por razão própria, ao
    # contrário de uma palavra plantada para o teste.
    assert 'id="itens"' in r.text
    assert "fila.js" in r.text
