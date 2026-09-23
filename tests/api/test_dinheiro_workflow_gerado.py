import json
from datetime import UTC, datetime

import pytest

# `api` é extra opcional (`pyproject.toml`). Sem a guarda, este arquivo
# derruba a COLETA da suíte inteira numa instalação `[dev]` — não só os
# próprios testes. Ver `.github/workflows/ci.yml`, que roda as duas variantes.
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.api import app as app_mod
from orchestrator.grill import catalogo as cat_mod
from orchestrator.grill.receita import Receita, ResolverReceita, para_json


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_RAIZ_FILA", tmp_path)
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    yield


def _gravar_pago(tmp_path) -> None:
    # "investigador", não "agente": o catálogo plano (Task 3) nomeia o bloco
    # AGENTE da conciliação pelo `Resolver.name` que ele sempre teve — o
    # cardápio do grill é que usava a chave "agente" só para propor este
    # mesmo bloco.
    r = Receita(
        id="pago",
        nome="Com agente",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=(ResolverReceita("L1", {}), ResolverReceita("investigador", {})),
    )
    destino = tmp_path / "workflows"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "pago.json").write_text(
        json.dumps(para_json(r), ensure_ascii=False), encoding="utf-8"
    )


def test_executar_workflow_com_agente_SEM_CHAVE_responde_409(tmp_path, monkeypatch):
    """Guarda 3. O 409 deixou de ser "isto nunca roda por aqui" e passou a ser
    "falta uma chave NESTE servidor" — e a recusa diz as duas saídas.

    `_tem_chave` é substituído em vez de lido do ambiente. Sem isso, este teste
    afirmaria uma coisa na máquina sem a variável e outra na máquina com ela, e
    a segunda é onde o dinheiro está.
    """
    monkeypatch.setattr(app_mod, "_tem_chave", lambda: False)
    _gravar_pago(tmp_path)
    cliente = TestClient(app_mod.app)

    resposta = cliente.post(
        "/api/workflows/pago/runs",
        # COM teto: ele e exigencia do PEDIDO e e conferida antes do 409.
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 60, "taxa_divergencia": 0.15},
              "teto_microcents": 1_000_000},
    )

    assert resposta.status_code == 409
    assert "CLI" in resposta.json()["detail"]
    assert "ANTHROPIC_API_KEY" in resposta.json()["detail"]


def test_sem_chave_o_modelo_nunca_e_chamado_por_um_endpoint(tmp_path, monkeypatch):
    # A outra metade: só o 409 passaria com a tranca quebrada. Espiona
    # `ClienteAusente.complete` e exige ZERO chamadas — se alguém um dia
    # trocar o sentinela por um cliente real NESTE caminho, este teste é quem
    # pega. A tranca continua sendo `ClienteAusente`; o que mudou é que existe
    # UM ponto onde ela é desarmada de propósito (`_cliente_de_execucao`), e
    # ele exige chave.
    monkeypatch.setattr(app_mod, "_tem_chave", lambda: False)
    _gravar_pago(tmp_path)
    chamadas = []
    original = cat_mod.ClienteAusente.complete

    def espiao(self, system, messages, tools):
        chamadas.append(1)
        return original(self, system, messages, tools)

    monkeypatch.setattr(cat_mod.ClienteAusente, "complete", espiao)
    cliente = TestClient(app_mod.app)

    cliente.post(
        "/api/workflows/pago/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 60, "taxa_divergencia": 0.15}},
    )
    cliente.get("/api/workflows/pago")
    cliente.get("/api/workflows")

    assert chamadas == []


def test_COM_chave_o_workflow_com_agente_deixa_de_ser_recusado(tmp_path, monkeypatch):
    """O outro lado da mesma regra, e a razão de esta fatia existir.

    Com chave, a cascata paga roda — e o 409 que a barrava some. O cliente de
    rede é substituído por um dublê: o que se prova aqui é o ROTEAMENTO da
    guarda, e provar roteamento indo à API paga seria pagar para saber o que um
    dublê responde de graça. Quanto ela gasta e onde o teto morde estão em
    `tests/api/test_execucao.py`.

    **O dublê ganhou RESPOSTAS.** Ele era `FakeLLMClient([])`, e isso bastava
    enquanto o `investigador` do catálogo declarava `kind="lancamento"`: cego,
    ele nunca chamava o cliente, e uma lista vazia nunca acabava. Com o bloco
    consertado o agente VÊ os lançamentos bancários que a cascata deixou em
    aberto, e um cliente sem respostas faria cada item morrer no
    `AssertionError` do dublê — o run continuaria 200 e a asserção continuaria
    verde, agora provando roteamento sobre um agente que só erra. Com respostas
    preparadas o que roda é o caminho feliz de verdade.
    """
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.agent.teto import ClienteComTeto, Orcamento
    from orchestrator.kernel.cost import Cost

    def _resposta() -> LLMResponse:
        """Uma resposta válida para o vocabulário do `investigador`."""
        return LLMResponse(
            text=(
                '{"tipo": "DEFASAGEM_TEMPORAL", "explicacao": "liquidou depois", '
                '"evidencia": ["o documento"], "confianca": "ALTA"}'
            ),
            tool_calls=[],
            cost=Cost(input_tokens=100, output_tokens=50),
        )

    monkeypatch.setattr(app_mod, "_tem_chave", lambda: True)
    def _de_execucao(teto):
        # Folga deliberada: o número de itens que sobra para o agente é
        # propriedade da fonte sintética e da cascata, não deste teste.
        #
        # A fábrica ignora o modelo — este teste é sobre a chave e o gasto, não
        # sobre roteamento de modelo — e o orçamento é um só, como na produção.
        fake = FakeLLMClient([_resposta()] * 200)
        orcamento = Orcamento(teto)
        return (lambda _model: ClienteComTeto(fake, orcamento=orcamento)), orcamento

    monkeypatch.setattr(app_mod, "_cliente_de_execucao", _de_execucao)
    _gravar_pago(tmp_path)
    cliente = TestClient(app_mod.app)

    resposta = cliente.post(
        "/api/workflows/pago/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 60, "taxa_divergencia": 0.15},
              "teto_microcents": 1_000_000},
    )

    assert resposta.status_code == 200, resposta.text
    assert "AGENTE" in [r["cost_class"] for r in resposta.json()["por_resolver"]]


def test_workflow_sem_agente_continua_executando(tmp_path):
    r = Receita(
        id="gratis",
        nome="Só regras",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=(ResolverReceita("L1", {}), ResolverReceita("L2", {})),
    )
    destino = tmp_path / "workflows"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "gratis.json").write_text(
        json.dumps(para_json(r), ensure_ascii=False), encoding="utf-8"
    )
    cliente = TestClient(app_mod.app)

    assert (
        cliente.post(
            "/api/workflows/gratis/runs",
            json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 60, "taxa_divergencia": 0.15}},
        ).status_code
        == 200
    )


def test_a_embutida_continua_executando(tmp_path):
    cliente = TestClient(app_mod.app)
    assert (
        cliente.post(
            "/api/workflows/conciliacao/runs",
            json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 60, "taxa_divergencia": 0.15}},
        ).status_code
        == 200
    )
