import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from orchestrator.api.app import app

cliente = TestClient(app)


def test_execucao_nao_chama_o_modelo_de_jeito_nenhum(monkeypatch):
    """A promessa do §5.2 do spec, virada teste — versão que de fato pina algo.

    A primeira versão deste teste levantava `AssertionError` de dentro de
    `AnthropicClient.complete` e checava só `status_code == 200`. Isso é
    vazio: `Investigator._uma()` (ver `investigator.py`) envolve exatamente
    essa chamada num `try/except Exception` largo e PROPOSITAL — qualquer
    exceção vinda do modelo, canário incluído, vira uma abstenção silenciosa
    e a rota devolve 200 do mesmo jeito. Medido: liguei um `Investigator` de
    verdade na definição servida e o teste antigo continuou passando. Uma
    exceção que o próprio domínio existe para engolir não prova que nada foi
    chamado.

    Por isso o canário aqui NUNCA levanta. Ele grava a chamada numa lista e
    devolve uma resposta válida — e a asserção é sobre a lista, não sobre
    propagação. Não existe `except` que esconda um `append`.
    """

    chamadas: list[dict] = []

    def _espiao(self, system, messages, tools):
        chamadas.append({"system": system, "messages": messages, "tools": tools})
        from orchestrator.agent.llm import LLMResponse
        from orchestrator.agent.proposal import Cost

        return LLMResponse(text="{}", tool_calls=[], cost=Cost.zero())

    # Qualquer construção de cliente real passa por aqui.
    import orchestrator.agent.anthropic_client as ac

    monkeypatch.setattr(ac.AnthropicClient, "complete", _espiao)

    resposta = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 100, "taxa_divergencia": 0.15},
    )

    assert resposta.status_code == 200
    assert chamadas == []


def test_execucao_so_serve_resolvers_de_classe_regra():
    """Segunda perna da mesma garantia, sem monkeypatch nenhum.

    Pina a propriedade direto na saída do endpoint: nenhum resolver de
    `cost_class` AGENTE participou da execução. Isso pega até um agente que
    foi ligado mas ABSTEVE em toda divergência sem nunca chamar o modelo —
    caso que o espião do teste acima não pegaria, porque para ele nada de
    errado aconteceria (a lista de chamadas continuaria vazia mesmo com o
    agente presente). As duas asserções são independentes: uma pega quem
    chama o modelo, a outra pega quem foi apenas colocado na cascata.
    """
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 100, "taxa_divergencia": 0.15},
    ).json()

    assert all(r["cost_class"] == "REGRA" for r in corpo["by_resolver"])


def test_execucao_reporta_taxa_e_custo_por_resolver():
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 0.15},
    ).json()

    nomes = [r["name"] for r in corpo["by_resolver"]]
    assert nomes == ["L1", "L2", "L3"]
    assert all(r["microcents"] == 0 for r in corpo["by_resolver"])
    assert 0.80 < corpo["deterministic_rate"] < 0.95


def test_a_lacuna_e_reportada_explicitamente():
    # A definição padrão não tem agente. O que as regras não resolvem não
    # some do relatório: vira lacuna com tamanho. É o §3.4 do spec de
    # composição — o ponto mais valioso da tela.
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 0.15},
    ).json()

    assert corpo["gap"]["items"] > 0
    soma = sum(r["rate"] for r in corpo["by_resolver"]) + corpo["gap"]["rate"]
    assert abs(soma - 1.0) < 1e-9


def test_n_invalido_da_422_em_vez_de_estourar():
    resposta = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 5.0},
    )
    assert resposta.status_code == 422
