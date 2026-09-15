import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from orchestrator.api.app import app

cliente = TestClient(app)


def test_execucao_nao_chama_o_modelo_de_jeito_nenhum(monkeypatch):
    """A promessa do §5.2 do spec, virada teste.

    Um endpoint HTTP apaga todas as barreiras que a CLI tem: um F5, um
    prefetch do navegador, uma aba esquecida aberta. Se algum dia alguém
    ligar o agente aqui, este teste quebra antes da fatura.
    """

    def _explode(*args, **kwargs):
        raise AssertionError("o endpoint tentou falar com o modelo")

    # Qualquer construção de cliente real passa por aqui.
    import orchestrator.agent.anthropic_client as ac

    monkeypatch.setattr(ac.AnthropicClient, "complete", _explode)

    resposta = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 100, "taxa_divergencia": 0.15},
    )

    assert resposta.status_code == 200


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
