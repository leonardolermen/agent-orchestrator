"""A fonte HTTP: uma página, com token por nome, e o servidor não vira proxy."""

import logging

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
        "http://127.1/x", "http://2130706433/x", "http://0x7f000001/x",
        "http://0177.0.0.1/x", "http://0.0.0.0/x", "http://[::]/x",
        "http://localhost./x", "http://LOCALHOST./x", "http://foo.localhost/x",
        "http://[::ffff:127.0.0.1]/x",
    ],
)
def test_loopback_link_local_e_esquema_estranho_sao_recusados_SEM_requisicao(monkeypatch, url):
    """O servidor passa a fazer requisições para URLs que vêm da tela. Recusar
    o que só o servidor alcança é o mínimo — e é recusado ANTES de sair."""
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]), url=url)
    with pytest.raises(FonteFalhou):
        fonte.load()
    assert pedidos == []


@pytest.mark.parametrize("url", ["https://abc.de/x", "https://api.exemplo/x"])
def test_nomes_dns_parecidos_com_numero_continuam_aceitos(monkeypatch, url):
    """Guarda contra over-refusal: um nome DNS todo em letras hex (`abc.de`)
    não é host numérico, mesmo parecendo um com o prefixo errado."""
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]), url=url)
    fonte.load()
    assert len(pedidos) == 1


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


def test_corpos_DIFERENTES_com_o_MESMO_etag_fraco_dao_refs_diferentes(monkeypatch):
    """O ETag saiu do `ref`, e este é o motivo mais afiado.

    Um ETag fraco (`W/"v1"`) significa por definição "equivalente, não
    idêntico", e um gateway que emite um ETag por VERSÃO DE API o mantém fixo
    enquanto a lista muda. Com o ETag no `ref`, dois pools distintos
    compartilhavam a chave de `data/fila/**` — e uma decisão humana tomada
    sobre o pool A era casada com os itens do pool B.
    """
    a, _ = _fonte(monkeypatch, _lista([{"id": 1}], ETag='W/"v1"'))
    b, _ = _fonte(monkeypatch, _lista([{"id": 2, "outro": "totalmente diferente"}], ETag='W/"v1"'))
    assert a.ref != b.ref


def test_o_MESMO_corpo_com_etags_diferentes_da_o_MESMO_ref(monkeypatch):
    """A direção oposta, e igualmente real: nginx e Apache derivam ETag de
    inode/mtime, e uma CDN o varia por nó. Bytes idênticos com ETags distintos
    davam `ref` distintos — chave de fila nova, decisões já tomadas invisíveis.
    """
    a, _ = _fonte(monkeypatch, _lista([{"id": 1}], ETag='"v7"'))
    b, _ = _fonte(monkeypatch, _lista([{"id": 1}], ETag='W/"outro-no-da-cdn"'))
    c, _ = _fonte(monkeypatch, _lista([{"id": 1}]))  # e sem ETag nenhum
    assert a.ref == b.ref == c.ref


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


def test_erro_de_transporte_e_reduzido_a_classe_e_o_texto_inteiro_vai_ao_LOG(
    monkeypatch, caplog
):
    """Simétrico com o gêmeo de Postgres: a resposta ao cliente leva só a
    classe — e o token NÃO —, e a mensagem inteira chega ao logger designado.
    Sem a asserção do `caplog`, o `_log.error` de `http.py` não teria teste
    nenhum e poderia sumir sem a suíte piscar."""

    def handler(p):
        raise httpx.ConnectError("boom to https://x with " + TOKEN)

    fonte, _ = _fonte(monkeypatch, handler)
    with caplog.at_level(logging.ERROR, logger="orchestrator.sources"):
        with pytest.raises(FonteFalhou) as erro:
            fonte.load()
    assert str(erro.value) == "requisição falhou: ConnectError"
    assert TOKEN not in str(erro.value)
    assert any(
        TOKEN in r.getMessage() and r.name == "orchestrator.sources" for r in caplog.records
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://usuario:SENHA-SECRETA@api.exemplo/x",
        "https://usuario@api.exemplo/x",
        "https://:SENHA-SECRETA@api.exemplo/x",
    ],
)
def test_url_com_usuario_ou_senha_embutidos_e_RECUSADA_sem_requisicao(monkeypatch, url):
    """httpx transforma userinfo em `Authorization: Basic …`, então a url
    FUNCIONA como autenticação — e a url inteira ia para o `ref`, que volta na
    resposta e é persistido em `data/runs/*.jsonl`. Recusar, não sanear."""
    fonte, pedidos = _fonte(monkeypatch, _lista([{"id": 1}]), url=url)
    with pytest.raises(FonteFalhou) as erro:
        fonte.load()
    assert pedidos == []
    assert "token_env" in str(erro.value)
    # A própria recusa não pode ecoar o que ela recusa.
    assert "SENHA-SECRETA" not in str(erro.value)


def test_o_ref_tambem_e_recusado_para_url_com_segredo(monkeypatch):
    """`ref` não passa por `load()`: se a guarda morasse lá, `fonte.ref` teria
    interpolado a senha mesmo assim."""
    fonte, pedidos = _fonte(
        monkeypatch, _lista([{"id": 1}]), url="https://usuario:SENHA-SECRETA@api.exemplo/x"
    )
    with pytest.raises(FonteFalhou):
        _ = fonte.ref
    assert pedidos == []


def _corpo_grande(tamanho):
    """Um corpo maior que o teto, servido em pedaços pelo transporte falso."""
    return lambda pedido: httpx.Response(200, content=b"x" * tamanho)


def test_o_teto_de_BYTES_recusa_antes_de_ler_o_corpo_inteiro(monkeypatch):
    fonte, _ = _fonte(monkeypatch, _corpo_grande(5000))
    pequena = HttpSource(
        url=fonte.url, token_env=fonte.token_env, kind=fonte.kind, campo_id=fonte.campo_id,
        max_bytes=100, transporte=fonte.transporte,
    )
    with pytest.raises(FonteFalhou, match="teto"):
        pequena.load()


def test_o_teto_de_BYTES_protege_o_REF_tambem(monkeypatch):
    """O teto mora no `_buscar`, não no `load()` — é a razão escrita no
    `ArquivoSource._bytes()`: `ref` não passa por `load()`, e um teto conferido
    só lá deixaria `fonte.ref` baixar o corpo inteiro em silêncio."""
    fonte, _ = _fonte(monkeypatch, _corpo_grande(5000))
    pequena = HttpSource(
        url=fonte.url, token_env=fonte.token_env, kind=fonte.kind, campo_id=fonte.campo_id,
        max_bytes=100, transporte=fonte.transporte,
    )
    with pytest.raises(FonteFalhou, match="teto"):
        _ = pequena.ref


def test_um_corpo_ABAIXO_do_teto_continua_passando(monkeypatch):
    """Guarda contra over-refusal: o teto não pode recusar o caso normal."""
    fonte, _ = _fonte(monkeypatch, _lista([{"id": 1}]))
    pequena = HttpSource(
        url=fonte.url, token_env=fonte.token_env, kind=fonte.kind, campo_id=fonte.campo_id,
        max_bytes=1024, transporte=fonte.transporte,
    )
    assert [i.id for i in pequena.load().items] == ["1"]


def test_sem_o_extra_a_falha_e_ALTA(monkeypatch):
    monkeypatch.setenv("CRM_TOKEN", TOKEN)
    monkeypatch.setitem(__import__("sys").modules, "httpx", None)
    fonte = HttpSource(url="https://api.exemplo/x", token_env="CRM_TOKEN", kind="k", campo_id="id")
    with pytest.raises(ExtraAusente, match=r"\[fontes\]"):
        fonte.load()
