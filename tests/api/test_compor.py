"""O compositor de cascata: o canvas de AUTORIA.

O §3.5 do spec de composição nomeia o modo de falha desta tela: **decoração** —
desenhar uma coisa e executar outra. A defesa não é visual, é estrutural, e
estes testes são o que a torna verificável:

  - a ORDEM não é um campo que o cliente envia; ela é derivada de `CostClass`;
  - o servidor devolve a definição CONSTRUÍDA, não a receita recebida;
  - `construir` valida, e a mensagem que a tela mostra é a do domínio.

Se um dia alguém acrescentar um campo de ordem, `test_a_ordem_enviada_e_IGNORADA`
fica vermelho — e é exatamente aí que a decoração começaria.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import orchestrator.api.app as app_mod
from orchestrator.api.app import app

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def receitas_em_tmp(tmp_path, monkeypatch):
    """Nunca o `data/` real do desenvolvedor — `gravar_receita` escreve."""
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    return tmp_path


def _corpo(resolvers, wid="minha-cascata"):
    return {
        "id": wid,
        "nome": "Minha cascata",
        "justificativa": "porque sim",
        "resolvers": resolvers,
    }


# -- o catálogo -------------------------------------------------------------


def test_o_catalogo_e_DERIVADO_do_CATALOGO_do_grill():
    """Uma lista escrita à mão na camada HTTP divergiria na primeira mudança, e
    o sintoma seria uma tela oferecendo um resolver que `construir` recusa."""
    from orchestrator.grill.catalogo import CATALOGO

    dados = cliente.get("/api/catalogo").json()

    assert {e["nome"] for e in dados} == set(CATALOGO)


def test_o_catalogo_vem_na_ordem_em_que_a_CASCATA_RODA():
    """Ordem alfabética sugeriria que o autor escolhe a sequência. Ele não
    escolhe: a paleta é oferecida do mais barato ao mais caro porque é essa a
    ordem de execução."""
    classes = [e["cost_class"] for e in cliente.get("/api/catalogo").json()]
    ordem = ["REGRA", "AGENTE", "CREW", "HUMANO"]

    assert classes == sorted(classes, key=ordem.index)


def test_o_catalogo_traz_os_parametros_com_DEFAULT_do_proprio_resolver():
    """`_param` lê o default do dataclass do resolver. A tela preenche com ele,
    então renomear o campo no resolver explode no import e não na tela."""
    l2 = next(e for e in cliente.get("/api/catalogo").json() if e["nome"] == "L2")

    assert {p["nome"] for p in l2["parametros"]} == {"max_cents", "max_business_days"}
    assert all(isinstance(p["default"], int) for p in l2["parametros"])
    assert all(p["descricao"] for p in l2["parametros"])


# -- a defesa contra decoração ---------------------------------------------


def test_a_ordem_enviada_e_IGNORADA():
    """O teste que impede esta tela de virar decoração.

    O cliente manda HUMANO antes de REGRA. O servidor devolve REGRA antes de
    HUMANO, porque quem ordena é `Stage.ordered()` e não existe entrada que a
    inverta. Se este teste ficar vermelho, alguém transformou a ordem num campo
    — e aí a tela passa a poder desenhar uma execução que não acontece.
    """
    corpo = _corpo([{"nome": "revisor"}, {"nome": "L1"}])

    r = cliente.post("/api/receitas", json=corpo)

    assert r.status_code == 201, r.text
    classes = [x["cost_class"] for x in r.json()["stages"][0]["cascade"]]
    assert classes == ["REGRA", "HUMANO"]


def test_a_resposta_e_a_definicao_CONSTRUIDA_e_nao_a_receita_enviada():
    """A tela mostra o que voltou do servidor. Se ela ecoasse o que o usuário
    montou, as duas coisas poderiam divergir sem sintoma."""
    r = cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}, {"nome": "L2"}]))

    cascata = r.json()["stages"][0]["cascade"]
    # `summary` não existe na receita enviada: ele vem do `describe()` do
    # resolver construído de verdade.
    assert all(x["summary"] for x in cascata)


# -- validar construindo ----------------------------------------------------


def test_resolver_desconhecido_devolve_a_mensagem_do_DOMINIO():
    """`construir` escreve erros para serem lidos — o grill depende disso para
    o modelo se corrigir, e a pessoa merece o mesmo texto."""
    r = cliente.post("/api/receitas", json=_corpo([{"nome": "inexistente"}]))

    assert r.status_code == 422
    assert "resolver desconhecido" in r.json()["detail"]
    assert "disponíveis" in r.json()["detail"]


def test_resolver_REPETIDO_e_recusado_com_o_motivo():
    """O segundo rodaria sobre o pool que o primeiro já esvaziou."""
    r = cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}, {"nome": "L1"}]))

    assert r.status_code == 422
    assert "esvaziou" in r.json()["detail"]


def test_parametro_desconhecido_e_recusado():
    r = cliente.post(
        "/api/receitas",
        json=_corpo([{"nome": "L2", "parametros": {"nao_existe": 3}}]),
    )

    assert r.status_code == 422
    assert "parâmetro desconhecido" in r.json()["detail"]


def test_cascata_VAZIA_e_recusada_antes_de_chegar_no_handler():
    r = cliente.post("/api/receitas", json=_corpo([]))

    assert r.status_code == 422


def test_id_invalido_usa_a_MESMA_validacao_do_grill():
    """Uma cópia da regra aqui divergiria, e o sintoma seria uma receita aceita
    pela tela e recusada pelo disco."""
    r = cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}], wid="Com Espaço"))

    assert r.status_code == 422


def test_id_JA_EXISTENTE_e_recusado_com_409():
    cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}], wid="repetida"))

    r = cliente.post("/api/receitas", json=_corpo([{"nome": "L2"}], wid="repetida"))

    assert r.status_code == 409
    assert "já existe" in r.json()["detail"]


def test_receita_que_NAO_constroi_nao_vai_para_o_disco(receitas_em_tmp):
    """Gravar antes de construir deixaria lixo que a listagem teria de filtrar
    para sempre."""
    cliente.post("/api/receitas", json=_corpo([{"nome": "inexistente"}], wid="ruim"))

    assert not list(receitas_em_tmp.rglob("ruim*"))


# -- a receita composta é um workflow de verdade ----------------------------


def test_a_receita_composta_APARECE_na_listagem_de_workflows():
    """O teste de que isto não é uma tela paralela: o que foi composto vira um
    workflow como qualquer outro, no mesmo registro."""
    cliente.post("/api/receitas", json=_corpo([{"nome": "L1"}], wid="composta"))

    ids = [w["id"] for w in cliente.get("/api/workflows").json()]

    assert "composta" in ids


def test_cascata_com_AGENTE_e_marcada_como_nao_executavel_pela_API():
    """A regra que governa o módulo HTTP: nenhum endpoint gasta dinheiro. A
    tela desabilita o botão em vez de deixar o usuário colher um 409."""
    cliente.post("/api/receitas", json=_corpo([{"nome": "agente"}], wid="cara"))

    w = next(x for x in cliente.get("/api/workflows").json() if x["id"] == "cara")

    assert w["executavel"] is False


# -- a página ---------------------------------------------------------------


def test_a_pagina_do_compositor_e_servida():
    r = cliente.get("/compor.html")

    assert r.status_code == 200
    assert 'id="catalogo"' in r.text
    assert "compor.js" in r.text


def test_a_pagina_DIZ_que_a_ordem_nao_e_do_autor():
    """A restrição mais importante da tela precisa estar escrita nela, não só
    no código. Quem abre o compositor tem de entender em dez segundos por que
    não há como arrastar para reordenar."""
    texto = cliente.get("/compor.html").text

    assert "ordem" in texto.lower()
    assert "classe de custo" in texto.lower()
