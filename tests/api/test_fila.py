import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.agent.proposal import Confidence, Proposal  # noqa: E402
from orchestrator.api.app import app  # noqa: E402
from orchestrator.review.fila import Fila, caminho_da_fila, dataset_id  # noqa: E402
from orchestrator.taxonomy import DivergenceType  # noqa: E402

cliente = TestClient(app)

PARAMS = {"seed": 1, "n": 30, "taxa_divergencia": 0.15}


@pytest.fixture(autouse=True)
def _fila_isolada(tmp_path, monkeypatch):
    """Cada teste com a sua raiz de fila, e o cache da execução limpo.

    Sem isolar a raiz, um teste escreveria decisões que outro leria. Sem
    limpar o cache, a execução memoizada serviria o estado anterior.
    """
    import orchestrator.api.app as modulo

    monkeypatch.setattr(modulo, "_RAIZ_FILA", tmp_path)
    modulo._executar_memoizado.cache_clear()
    yield
    modulo._executar_memoizado.cache_clear()


def _grava_proposta(divergence_id: str, **overrides) -> None:
    """Escreve uma proposta direto na fila isolada do teste em curso.

    A Task 10 (CLI grava propostas de verdade) ainda não existe: até lá, os
    testes de rota precisam colocar a proposta na fila eles mesmos, do mesmo
    jeito que `tests/agent/test_investigator.py` já faz.
    """
    import orchestrator.api.app as modulo

    campos = {
        "divergence_id": divergence_id,
        "tipo": DivergenceType.DEFASAGEM_TEMPORAL,
        "explicacao": "atraso de compensação bancária",
        "evidencia": ["extrato e razão citam o mesmo documento"],
        "confianca": Confidence.MEDIA,
        "acao_sugerida": "conciliar_com(l00003)",
    }
    campos.update(overrides)
    caminho = caminho_da_fila("conciliacao", dataset_id(1, 30, 0.15), raiz=modulo._RAIZ_FILA)
    Fila(caminho).gravar_proposta(Proposal(**campos))


def test_fila_vazia_devolve_lista_vazia():
    corpo = cliente.get("/api/fila/conciliacao", params=PARAMS).json()

    assert corpo["itens"] == []
    assert corpo["dataset"] == "s1-n30-t0.15"


def test_workflow_desconhecido_da_404():
    r = cliente.get("/api/fila/nao-existe", params=PARAMS)

    assert r.status_code == 404


def test_decidir_divergencia_sem_proposta_da_404():
    r = cliente.post(
        "/api/fila/conciliacao/d-b-inexistente/decisao",
        params=PARAMS,
        json={"veredito": "aceitar", "autor": "a"},
    )

    assert r.status_code == 404


def test_corrigir_sem_tipo_da_422():
    r = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params=PARAMS,
        json={"veredito": "corrigir", "autor": "a"},
    )

    assert r.status_code == 422


def test_ler_a_fila_nao_chama_o_modelo(monkeypatch):
    # A mesma regra do endpoint de execução: nenhuma rota tem caminho até o
    # modelo. Asserção sobre o estado do espião, nunca sobre exceção
    # propagada — a técnica por exceção foi provada vazia (P3.8).
    import orchestrator.agent.anthropic_client as ac

    chamadas = []
    monkeypatch.setattr(
        ac.AnthropicClient, "complete",
        lambda self, system, messages, tools: chamadas.append(1),
    )

    assert cliente.get("/api/fila/conciliacao", params=PARAMS).status_code == 200
    assert chamadas == []


def test_execucao_so_serve_classes_que_nao_gastam():
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 30, "taxa_divergencia": 0.15},
    ).json()

    assert all(r["cost_class"] != "AGENTE" for r in corpo["by_resolver"])
    assert "revisor" in [r["name"] for r in corpo["by_resolver"]]


def test_a_soma_das_taxas_mais_a_lacuna_continua_um():
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 0.15},
    ).json()

    soma = sum(r["rate"] for r in corpo["by_resolver"]) + corpo["gap"]["rate"]
    assert abs(soma - 1.0) < 1e-9


def test_aceitar_acao_malformada_da_422():
    # `acao_sugerida` só é validada por `startswith` antes de chegar na fila
    # (ver `investigator.py`) — "conciliar_com:l1" (sem parênteses) passa por
    # aquela checagem e já apareceu em fixtures deste repositório.
    # `ids_de_conciliar_com` devolve vazio para essa forma quebrada. Aceitar
    # sem checar gravaria uma decisão que não concilia nada, sem erro nenhum.
    _grava_proposta("d-b-b00003", acao_sugerida="conciliar_com:l1")

    r = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params=PARAMS,
        json={"veredito": "aceitar", "autor": "a"},
    )

    assert r.status_code == 422


def test_aceitar_investigar_manual_ainda_aceita():
    # `investigar_manual` legitimamente não concilia nada — não é malformada,
    # é uma abstenção. O guard do teste acima não pode pegar este caso.
    _grava_proposta(
        "d-b-b00003",
        tipo=DivergenceType.NAO_IDENTIFICADO,
        confianca=Confidence.BAIXA,
        evidencia=[],
        acao_sugerida="investigar_manual",
    )

    r = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params=PARAMS,
        json={"veredito": "aceitar", "autor": "a"},
    )

    assert r.status_code == 200


def test_decisao_aceitar_atualiza_a_execucao_apos_invalidar_cache():
    """`cache_clear()` é a única coisa que impede o canvas de mentir.

    Na semente 1/n=30/taxa=0.15 sobram exatamente duas divergências sem
    resolução determinística: `d-b-b00003` e `d-l-l00003` (o mesmo par —
    verificado rodando `reconcile` direto sobre o benchmark). Antes de
    qualquer decisão a lacuna do canvas tem 1 item bancário aberto. Aceitar a
    proposta que concilia os dois deve fechar essa lacuna na PRÓXIMA leitura
    do endpoint de execução — o que só acontece se o POST limpar o cache.
    """
    corpo_execucao = {"seed": 1, "n": 30, "taxa_divergencia": 0.15}

    antes = cliente.post("/api/workflows/conciliacao/runs", json=corpo_execucao).json()
    assert antes["gap"]["items"] == 1

    _grava_proposta("d-b-b00003", acao_sugerida="conciliar_com(l00003)")

    r = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params=PARAMS,
        json={"veredito": "aceitar", "autor": "controller@cliente"},
    )
    assert r.status_code == 200

    depois = cliente.post("/api/workflows/conciliacao/runs", json=corpo_execucao).json()
    assert depois["gap"]["items"] == 0
    revisor = next(r2 for r2 in depois["by_resolver"] if r2["name"] == "revisor")
    assert revisor["matches"] == 1
