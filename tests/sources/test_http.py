"""A fonte HTTP: uma página, com token por nome, e o servidor não vira proxy."""

import httpx
import pytest

from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente
from orchestrator.sources.http import HttpSource

TOKEN = "SEGREDO-4F2A"


def _fonte(
    monkeypatch, responder, *, url="https://api.exemplo/issues", token="CRM_TOKEN",
    caminho="", env=TOKEN,
):
    """`MockTransport` responde sem rede; `pedidos` guarda o que saiu para que
    o teste veja o cabeçalho de autorização e conte as requisições."""
    if env is not None:
        monkeypatch.setenv("CRM_TOKEN", env)
    else:
        monkeypatch.delenv("CRM_TOKEN", raising=False)
    pedidos = []

    def handler(pedido):
        pedidos.append(pedido)
        return responder(pedido)

    fonte = HttpSource(
        url=url, token_env=token, kind="issue", campo_id="id", caminho=caminho,
        transporte=httpx.MockTransport(handler),
    )
    return fonte, pedidos


def _lista(itens, **cabecalhos):
    return lambda pedido: httpx.Response(200, json=itens, headers=cabecalhos)


def test_a_lista_do_corpo_vira_pool(monkeypatch):
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 7, "titulo": "trava"}]))
    pool = fonte.load()
    assert [i.id for i in pool.items] == ["7"]
    assert pool.items[0].payload == {"id": 7, "titulo": "trava"}
    assert pedidos[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_caminho_aponta_a_lista_dentro_do_corpo(monkeypatch):
    fonte, _ = _fonte(
        monkeypatch, lambda p: httpx.Response(200, json={"dados": {"itens": [{"id": 1}]}}),
        caminho="dados.itens",
    )
    assert [i.id for i in fonte.load().items] == ["1"]


def test_sem_token_env_nao_manda_Authorization(monkeypatch):
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]), token=None)
    fonte.load()
    assert "Authorization" not in pedidos[0].headers


def test_variavel_ausente_e_erro_que_cita_o_NOME_e_nao_faz_requisicao(monkeypatch):
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]), env=None)
    with pytest.raises(VariavelAusente, match="CRM_TOKEN"):
        fonte.load()
    assert pedidos == []


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x", "http://127.0.0.1/x", "http://127.9.9.9/x",
        "http://[::1]/x", "http://169.254.1.1/x", "ftp://api.exemplo/x", "api.exemplo/x",
    ],
)
def test_loopback_link_local_e_esquema_estranho_sao_recusados_SEM_requisicao(monkeypatch, url):
    """O servidor passa a fazer requisições para URLs que vêm da tela. Recusar
    o que só o servidor alcança é o mínimo — e é recusado ANTES de sair."""
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]), url=url)
    with pytest.raises(FonteFalhou):
        fonte.load()
    assert pedidos == []


def test_status_nao_2xx_e_erro_com_status_e_url_e_NUNCA_o_token(monkeypatch):
    fonte, _ = _fonte(monkeypatch, lambda p: httpx.Response(401, text=f"bad token {TOKEN}"))
    with pytest.raises(FonteFalhou) as erro:
        fonte.load()
    assert "401" in str(erro.value) and "https://api.exemplo/issues" in str(erro.value)
    assert TOKEN not in str(erro.value)


def test_corpo_que_nao_e_lista_e_recusado_dizendo_o_que_veio(monkeypatch):
    fonte, _ = _fonte(monkeypatch, lambda p: httpx.Response(200, json={"ok": True}))
    with pytest.raises(FonteFalhou, match="lista"):
        fonte.load()


def test_o_ref_usa_o_ETAG_quando_ha(monkeypatch):
    fonte, _ = _fonte(monkeypatch, _lista([{"id": 1}], ETag='"v7"'))
    assert fonte.ref == 'http:https://api.exemplo/issues@"v7"'


def test_sem_etag_o_ref_e_o_hash_do_corpo_e_e_ESTAVEL(monkeypatch):
    a, _ = _fonte(monkeypatch, _lista([{"id": 1}]))
    b, _ = _fonte(monkeypatch, _lista([{"id": 1}]))
    c, _ = _fonte(monkeypatch, _lista([{"id": 2}]))
    assert a.ref == b.ref and a.ref != c.ref
    assert a.ref.startswith("http:https://api.exemplo/issues@")
    assert TOKEN not in a.ref


def test_ref_e_load_sao_UMA_requisicao(monkeypatch):
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]))
    _ = fonte.ref
    fonte.load()
    assert len(pedidos) == 1


def test_erro_de_transporte_e_reduzido_a_classe(monkeypatch):
    def handler(p):
        raise httpx.ConnectError("boom to https://x with " + TOKEN)

    fonte, _ = _fonte(monkeypatch, handler)
    with pytest.raises(FonteFalhou) as erro:
        fonte.load()
    assert str(erro.value) == "requisição falhou: ConnectError"


def test_sem_o_extra_a_falha_e_ALTA(monkeypatch):
    monkeypatch.setenv("CRM_TOKEN", TOKEN)
    monkeypatch.setitem(__import__("sys").modules, "httpx", None)
    fonte = HttpSource(url="https://api.exemplo/x", token_env="CRM_TOKEN", kind="k", campo_id="id")
    with pytest.raises(ExtraAusente, match=r"\[fontes\]"):
        fonte.load()
