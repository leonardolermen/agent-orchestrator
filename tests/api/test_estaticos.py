import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from orchestrator.api.app import app

cliente = TestClient(app)


def test_a_raiz_serve_a_pagina():
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]
    # Não `"conciliar" in resposta.text.lower()`: a palavra só está em
    # `index.html` porque este teste a exigiu — quase se autoconfirma. As
    # duas checagens abaixo ancoram em propriedades que a página tem por
    # motivo próprio: `id="stages"` é o mount point em que `canvas.js`
    # escreve, e sem a referência ao script a página nunca desenha nada.
    assert 'id="stages"' in resposta.text
    assert "canvas.js" in resposta.text
