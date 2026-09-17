"""A tela servida pela API: UMA aplicação, não três páginas.

Até esta fatia havia dois frontends — `web/index.html` + `canvas.js` (o canvas
medido), `web/fila.html` + `fila.js` (a fila de revisão) e, dentro de `web/`,
o build do app React em `/compor/`. A duplicação não era teórica: o "modo
escuro por default" foi implementado no app React e nunca nas duas páginas
estáticas, então a tela que o README mandava abrir primeiro abria clara.

Um frontend só é o que torna aquele defeito impossível de repetir, e é isso
que estes testes ancoram.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.api.app import app  # noqa: E402

cliente = TestClient(app)


def test_a_raiz_serve_o_app():
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]
    # Âncoras estruturais, não palavras plantadas para o teste: `id="raiz"` é
    # o ponto de montagem em que `main.tsx` escreve, e sem o módulo a página
    # nunca desenha nada.
    assert 'id="raiz"' in resposta.text
    assert 'type="module"' in resposta.text


def test_a_raiz_JA_CHEGA_escura_sem_depender_do_bundle():
    """O teste que existe por causa de um bug real.

    O escuro é decisão de PRODUTO, e uma decisão de produto que só vale depois
    que 361 kB de JavaScript baixam e executam não é um default — é um
    conserto tardio, com um flash claro antes.

    Por isso o tema é aplicado por um script INLINE no `<head>`, que roda
    antes da primeira pintura, e é a presença dele no HTML SERVIDO que este
    teste ancora. Um `<script type="module">` não serve: módulo é adiado por
    especificação, e roda depois de o CSS já ter pintado.
    """
    html = cliente.get("/").text

    assert "classList.add" in html, "o tema não é aplicado no HTML servido"
    assert '"dark"' in html
    # A AUSÊNCIA de preferência cai no escuro, nunca no claro. Se esta
    # comparação virar `=== "dark"`, o default silenciosamente inverte.
    assert 'localStorage.getItem("tema") === "light"' in html or \
           "localStorage.getItem('tema') === 'light'" in html


def test_a_fila_e_a_MESMA_pagina_que_o_canvas():
    """Uma aplicação, duas vistas — e é isso que mata o defeito do P4.14.

    Enquanto eram duas páginas, o canvas e a fila precisavam CONCORDAR sobre
    qual fila estavam olhando, e a coordenação dependia de as duas lerem a
    mesma query string. O `DECISOES.md` registra que essa promessa já quebrou
    uma vez. Com uma página só, `seed`/`n`/`taxa_divergencia` viram estado
    único: não há com quem discordar.
    """
    resposta = cliente.get("/?vista=fila&seed=1&n=30&taxa_divergencia=0.15")

    assert resposta.status_code == 200
    assert 'id="raiz"' in resposta.text


def test_as_paginas_estaticas_nao_existem_mais():
    """A metade "apagar" da migração, ancorada.

    Sem isto, um `fila.html` esquecido continuaria sendo servido — claro,
    divergente, e encontrável por quem seguisse um link antigo.
    """
    assert cliente.get("/fila.html").status_code == 404
    assert cliente.get("/canvas.js").status_code == 404
    assert cliente.get("/style.css").status_code == 404
