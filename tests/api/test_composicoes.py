"""O endpoint de composição: a paleta deixou de ser o cardápio da conciliação.

`/api/receitas` compõe a partir de NOMES do catálogo do grill. Serve enquanto
tudo que se compõe já existe pronto — e foi por isso que o canvas ofereceu só
blocos de conciliação até alguém perguntar por quê.

`/api/composicoes` compõe a partir de BLOCOS: uma regra do catálogo com
parâmetros, ou um agente inteiro, criado ali, que não existe em catálogo nenhum.

O teste que carrega o peso é `test_um_agente_INVENTADO_na_tela_vira_cascata`: se
ele ficar vermelho, voltou a ser preciso escrever Python para ter um agente.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import orchestrator.api.app as app_mod
from orchestrator.api.app import app

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def composicoes_em_tmp(tmp_path, monkeypatch):
    """Nunca o `data/` real do desenvolvedor — `gravar` escreve."""
    monkeypatch.setattr(app_mod, "_RAIZ_COMPOSICOES", tmp_path)
    return tmp_path


def _agente(**kw):
    declaracao = {
        "name": "meu-triador",
        "system": "classifique a issue",
        "kind": "issue",
        "prompt": "{titulo}\n\n{corpo}",
        "tipos": ["BUG", "FEATURE"],
        "abstem_com": "NAO_SEI",
        "ferramentas": [],
        "max_turns": 3,
        "budget_microcents": 4_000_000,
    }
    declaracao.update(kw)
    return {"tipo": "agente", "declaracao": declaracao}


def _corpo(blocos, cid="minha-cascata"):
    return {
        "id": cid,
        "nome": "Minha cascata",
        "justificativa": "porque sim",
        "blocos": blocos,
    }


# -- o que a receita não sabia carregar -------------------------------------


def test_um_agente_INVENTADO_na_tela_vira_cascata():
    """A prova de que a plataforma é geral, pela borda HTTP.

    Nada deste agente existe em catálogo nenhum: nome, prompt, vocabulário e
    orçamento chegaram na requisição. Se isto exigisse Python, o canvas voltaria
    a ser um cardápio de coisas prontas.
    """
    r = cliente.post("/api/composicoes", json=_corpo([_agente()]))

    assert r.status_code == 201, r.text
    (bloco,) = r.json()["stages"][0]["cascade"]
    assert bloco["name"] == "meu-triador"
    assert bloco["cost_class"] == "AGENTE"


def test_a_resposta_e_a_definicao_CONSTRUIDA_e_nao_o_que_foi_enviado():
    """`summary` não existe no corpo enviado: ele vem do `describe()` do
    resolver construído de verdade."""
    r = cliente.post("/api/composicoes", json=_corpo([_agente()]))

    assert all(x["summary"] for x in r.json()["stages"][0]["cascade"])


# -- a defesa contra decoração ---------------------------------------------


def test_a_ordem_enviada_e_IGNORADA():
    """O mesmo teste que protege `/api/receitas`, agora no formato geral.

    O cliente manda o AGENTE antes da REGRA. O servidor devolve REGRA antes de
    AGENTE, porque quem ordena é `Stage.ordered()` e não existe campo de ordem.
    """
    corpo = _corpo(
        [
            _agente(name="buscador-meu", kind="requisicao"),
            {"tipo": "regra", "nome": "preferido"},
        ]
    )

    r = cliente.post("/api/composicoes", json=corpo)

    assert r.status_code == 201, r.text
    classes = [x["cost_class"] for x in r.json()["stages"][0]["cascade"]]
    assert classes == ["REGRA", "AGENTE"]


# -- validar construindo, com a mensagem do domínio -------------------------


def test_vocabulario_que_COLIDE_com_a_abstencao_e_recusado_com_a_medida():
    """A invariante do P6.86 chegando até a tela.

    `DUVIDA` como tipo E como rótulo de "não sei" tirou 16 de 50 casos do
    denominador da precisão. A mensagem carrega esse fato — a pessoa que compõe
    precisa saber por que está sendo barrada.
    """
    r = cliente.post(
        "/api/composicoes",
        json=_corpo([_agente(tipos=["BUG", "NAO_SEI"], abstem_com="NAO_SEI")]),
    )

    assert r.status_code == 422
    assert "rótulo de abstenção" in r.json()["detail"]


def test_prompt_que_nao_interpola_NADA_e_recusado():
    """Todo item receberia o mesmo texto, e o agente responderia sem ler o
    item. É caro e silencioso: a conta vem, a medida não."""
    r = cliente.post("/api/composicoes", json=_corpo([_agente(prompt="classifique")]))

    assert r.status_code == 422
    assert "não interpola" in r.json()["detail"]


def test_bloco_FORA_do_catalogo_e_recusado_listando_os_disponiveis():
    """A mensagem que a tela mostra é a do domínio, e ela precisa dizer o que
    HÁ — quem compõe (e o modelo, no chat) se corrige com a lista."""
    r = cliente.post(
        "/api/composicoes",
        json=_corpo([{"tipo": "regra", "nome": "nao-existe"}]),
    )

    assert r.status_code == 422
    assert "bloco desconhecido no catálogo" in r.json()["detail"]
    assert "disponíveis" in r.json()["detail"]


def test_um_agente_de_KIND_qualquer_e_ACEITO():
    """O quadro em branco chegando à borda HTTP.

    `kind="lancamento"` num agente inventado era recusado com "não é do
    domínio", porque o pedido carregava um domínio e o catálogo era
    particionado por ele. A checagem saiu porque, com a tela sem seletor, toda
    composição chegava com o domínio default e ela recusava todo kind que não
    fosse `"lancamento"` — cascata válida barrada pelo motivo errado.

    **O que este teste afirma, e o que não afirma.** Afirma que a composição
    é ACEITA ao salvar: ela não conhece a fonte, e "valida construindo"
    continua sendo a garantia. NÃO afirma que `lancamento` é um kind que
    alguma fonte produz — hoje nenhuma produz. A guarda que pega isso mora na
    BORDA do `/runs`, por resolver, contra os kinds da fonte que vai rodar
    (`tests/api/test_execucao.py::test_a_borda_recusa_bloco_que_a_fonte_NAO_alimenta`),
    e `Stage.consome` passou a carregar o kind para ela ler
    (`tests/test_fiacao_derivada.py`). A guarda antiga — partição de catálogo
    — saiu porque recusava cascata válida; esta compara o grafo que VAI
    rodar com a fonte que VAI rodar.
    """
    r = cliente.post("/api/composicoes", json=_corpo([_agente(kind="lancamento")]))

    assert r.status_code == 201, r.text


def test_a_cascata_com_o_degrau_HUMANO_COMPOE_pela_borda_HTTP():
    """O defeito, no caminho em que ele aparecia: paleta → clique → 422.

    `/api/catalogo` serve toda `CATALOGO.regras`, então `revisor` está na
    paleta do canvas. Clicar nele e apertar "Compor e validar" postava um
    bloco `regra`, e `construir_composicao` chamava `regra.construir({})` sem
    olhar a classe — o que devolvia 422 com a mensagem de
    `_revisor_precisa_da_fila`, escrita para quem implementa e exibida para
    quem usa. Era o único bloco da paleta que a composição não compunha, e
    logo o degrau que FECHA a cascata.
    """
    r = cliente.post(
        "/api/composicoes",
        json=_corpo([{"tipo": "regra", "nome": "L1"}, {"tipo": "regra", "nome": "revisor"}]),
    )

    assert r.status_code == 201, r.text
    cascata = r.json()["stages"][0]["cascade"]
    assert [b["cost_class"] for b in cascata] == ["REGRA", "HUMANO"]


def test_bloco_REPETIDO_e_recusado_com_o_motivo():
    corpo = _corpo(
        [
            {"tipo": "regra", "nome": "preferido"},
            {"tipo": "regra", "nome": "preferido"},
        ]
    )

    r = cliente.post("/api/composicoes", json=corpo)

    assert r.status_code == 422
    assert "esvaziou" in r.json()["detail"]


def test_parametro_desconhecido_de_REGRA_e_recusado():
    corpo = _corpo(
        [{"tipo": "regra", "nome": "L2", "parametros": {"nao_existe": 3}}]
    )

    r = cliente.post("/api/composicoes", json=corpo)

    assert r.status_code == 422
    assert "parâmetro desconhecido" in r.json()["detail"]


def test_tipo_de_bloco_desconhecido_e_recusado_pelo_SCHEMA():
    """União discriminada, não dicionário de campos opcionais: o Pydantic recusa
    antes do handler rodar, e diz qual dos dois formatos esperava."""
    r = cliente.post("/api/composicoes", json=_corpo([{"tipo": "futuro", "nome": "x"}]))

    assert r.status_code == 422


def test_id_invalido_e_recusado_pela_MESMA_validacao_do_disco():
    r = cliente.post("/api/composicoes", json=_corpo([_agente()], cid="../fora"))

    assert r.status_code == 422


# -- gravar não é escrever num buraco ---------------------------------------


def test_o_que_foi_composto_APARECE_na_listagem():
    cliente.post("/api/composicoes", json=_corpo([_agente()]))

    (c,) = cliente.get("/api/composicoes").json()

    assert c["id"] == "minha-cascata"
    assert "dominio" not in c
    # NOMES e não contagem: "1 bloco" não distingue uma cascata que começa numa
    # regra barata de uma que começa direto no modelo.
    assert c["blocos"] == ["meu-triador"]
    assert c["version"]


def test_id_REPETIDO_e_409_e_nao_sobrescreve():
    """Runs antigos apontam para a composição pela versão; trocar o conteúdo sob
    o mesmo id faria um run apontar para uma cascata que nunca rodou."""
    cliente.post("/api/composicoes", json=_corpo([_agente()]))

    r = cliente.post("/api/composicoes", json=_corpo([_agente(name="outro")]))

    assert r.status_code == 409
    (c,) = cliente.get("/api/composicoes").json()
    assert c["blocos"] == ["meu-triador"]


def test_composicao_que_NAO_CONSTROI_nao_vai_para_o_disco():
    """Mesma ordem de `/api/receitas`: grava só depois de construir."""
    cliente.post("/api/composicoes", json=_corpo([_agente(prompt="sem campo")]))

    assert cliente.get("/api/composicoes").json() == []


# -- a regra do módulo ------------------------------------------------------


def test_compor_uma_cascata_PAGA_nao_gasta_nada():
    """A cascata tem classe AGENTE e ainda assim compor é grátis: o cliente
    default de `construir_composicao` é a tranca, não um modelo. Se alguém
    trocasse esse default, este teste estouraria com o texto da recusa."""
    r = cliente.post("/api/composicoes", json=_corpo([_agente()]))

    assert r.status_code == 201
    assert any(x["cost_class"] == "AGENTE" for x in r.json()["stages"][0]["cascade"])
