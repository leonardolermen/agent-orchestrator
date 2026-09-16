"""O histórico de execuções — o que o `lru_cache` tornava impossível."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.api.app import app  # noqa: E402

cliente = TestClient(app)
PEDIDO = {"seed": 1, "n": 30, "taxa_divergencia": 0.15}


def test_executar_persiste_o_run_e_ele_aparece_no_historico():
    """Antes do PR #7 isto era impossível de perguntar.

    A "execução" era uma entrada num `lru_cache` de 64 posições, sem id, sem
    timestamp e sem estado. "O que aconteceu no fechamento de agosto" não tinha
    resposta.
    """
    assert cliente.post("/api/workflows/conciliacao/runs", json=PEDIDO).status_code == 200

    runs = cliente.get("/api/runs").json()

    assert len(runs) == 1
    assert runs[0]["workflow_id"] == "conciliacao"
    assert runs[0]["input_ref"] == "synth:s1-n30-t0.15"
    assert runs[0]["resolved"] > 0
    assert runs[0]["duration_ms"] is not None


def test_cada_execucao_e_um_run_novo_sem_cache_no_meio():
    """Duas chamadas iguais produzem DOIS runs, não um cacheado.

    É a diferença entre um store e uma memoização: o store registra o que
    aconteceu, e aconteceu duas vezes.
    """
    for _ in range(2):
        cliente.post("/api/workflows/conciliacao/runs", json=PEDIDO)

    runs = cliente.get("/api/runs").json()

    assert len(runs) == 2
    assert runs[0]["id"] != runs[1]["id"]


def test_historico_vem_mais_recente_primeiro():
    for n in (30, 40):
        cliente.post("/api/workflows/conciliacao/runs", json={**PEDIDO, "n": n})

    runs = cliente.get("/api/runs").json()

    assert [r["id"] for r in runs] == sorted((r["id"] for r in runs), reverse=True)


def test_obter_run_por_id():
    cliente.post("/api/workflows/conciliacao/runs", json=PEDIDO)
    rid = cliente.get("/api/runs").json()[0]["id"]

    assert cliente.get(f"/api/runs/{rid}").json()["id"] == rid


def test_run_desconhecido_da_404():
    assert cliente.get("/api/runs/nao-existe").status_code == 404


def test_estado_invalido_da_422_e_nao_500():
    """Mesma disciplina de `RunRequest`: parâmetro inválido é 422, não 500."""
    r = cliente.get("/api/runs", params={"state": "inventado"})

    assert r.status_code == 422
    assert "estado desconhecido" in r.json()["detail"]


def test_filtra_por_estado():
    cliente.post("/api/workflows/conciliacao/runs", json=PEDIDO)

    # A cascata padrão tem revisor (classe HUMANO) e sobram divergências, então
    # o run espera alguém — o estado que antes era implícito.
    assert cliente.get("/api/runs", params={"state": "aguardando_humano"}).json()
    assert cliente.get("/api/runs", params={"state": "concluido"}).json() == []


def test_a_rota_de_runs_nao_gasta_dinheiro():
    """A regra do módulo vale para as rotas novas também.

    Não é flag: não existe caminho de código daqui até o modelo. O teste
    existe para que a rota nova não vire a exceção.
    """
    import orchestrator.agent.anthropic_client as ac

    chamou = []
    original = ac.AnthropicClient.complete
    ac.AnthropicClient.complete = lambda *a, **k: chamou.append(1)
    try:
        cliente.post("/api/workflows/conciliacao/runs", json=PEDIDO)
        cliente.get("/api/runs")
    finally:
        ac.AnthropicClient.complete = original

    assert chamou == []
