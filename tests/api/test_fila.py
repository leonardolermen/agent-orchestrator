import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.api.app import app  # noqa: E402
from orchestrator.kernel.resolution import Confidence, Proposal  # noqa: E402
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
    yield


def _grava_proposta(divergence_id: str, **overrides) -> None:
    """Escreve uma proposta direto na fila isolada do teste em curso.

    A Task 10 (CLI grava propostas de verdade) ainda não existe: até lá, os
    testes de rota precisam colocar a proposta na fila eles mesmos, do mesmo
    jeito que `tests/agent/test_investigator.py` já faz.
    """
    import orchestrator.api.app as modulo

    campos = {
        "item_id": divergence_id,
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
    #
    # Com a fila VAZIA este teste passaria mesmo que `_item` chamasse o
    # modelo, porque `_item` nunca roda sobre lista vazia — ele passaria por
    # engano, não por prova. Uma proposta pendente de verdade é o que faz o
    # laço de montagem de item executar.
    _grava_proposta("d-b-b00003")

    import orchestrator.agent.anthropic_client as ac

    chamadas = []
    monkeypatch.setattr(
        ac.AnthropicClient, "complete",
        lambda self, system, messages, tools: chamadas.append(1),
    )

    r = cliente.get("/api/fila/conciliacao", params=PARAMS)
    assert r.status_code == 200
    assert r.json()["itens"] != []
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


def test_corrigir_com_id_inexistente_da_422_e_nao_grava():
    # Mesma falha do `aceitar` malformado, do lado humano: um id que não
    # existe em nenhum dos dois lados do dataset chega intacto até
    # `revisor.py`, que marca a decisão inteira "obsoleta" e a DESCARTA sem
    # erro — o item some de `pendentes()`, `divergiu` acusa divergência do
    # agente, o log registra uma "correção aprovada", e nenhum vínculo nasce.
    _grava_proposta("d-b-b00003")
    import orchestrator.api.app as modulo

    caminho = caminho_da_fila("conciliacao", dataset_id(1, 30, 0.15), raiz=modulo._RAIZ_FILA)
    linhas_antes = len(caminho.read_text(encoding="utf-8").strip().splitlines())

    r = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params=PARAMS,
        json={
            "veredito": "corrigir",
            "tipo": "DEFASAGEM_TEMPORAL",
            "conciliar_com": ["id-fantasma"],
            "autor": "a",
        },
    )

    assert r.status_code == 422
    # O 422 precisa impedir a escrita, não só o efeito: nenhuma linha nova no
    # arquivo append-only.
    linhas_depois = len(caminho.read_text(encoding="utf-8").strip().splitlines())
    assert linhas_depois == linhas_antes


def test_corrigir_com_conciliar_com_vazio_ainda_aceita():
    # Corrigir só o TIPO, sem conciliar nada, é uma abstenção legítima — a
    # mesma classe de "isto reconcilia zero" que `investigar_manual` já é.
    # O guard do teste acima não pode confundir isto com id inexistente.
    #
    # `conciliar_com` na resposta é o que a PROPOSTA sugeriu (`_item` lê de
    # `proposta.acao_sugerida`, não da decisão) — por isso a asserção aqui é
    # sobre o que a decisão de fato gravou, via `tipo_decidido`, não sobre
    # esse campo.
    _grava_proposta("d-b-b00003")
    import orchestrator.api.app as modulo
    from orchestrator.review.fila import Fila as _Fila

    r = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params=PARAMS,
        json={"veredito": "corrigir", "tipo": "DEFASAGEM_TEMPORAL", "autor": "a"},
    )

    assert r.status_code == 200
    assert r.json()["tipo_decidido"] == "DEFASAGEM_TEMPORAL"
    caminho = caminho_da_fila("conciliacao", dataset_id(1, 30, 0.15), raiz=modulo._RAIZ_FILA)
    decisao = _Fila(caminho).decisao("d-b-b00003")
    assert decisao.conciliar_com == frozenset()


def test_seed_taxa_invalidos_na_leitura_da_fila_dao_422_nao_500():
    r = cliente.get(
        "/api/fila/conciliacao",
        params={"seed": 1, "n": 30, "taxa_divergencia": 5.0},
    )

    assert r.status_code == 422


def test_seed_taxa_invalidos_na_decisao_dao_422_nao_500():
    r = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params={"seed": 1, "n": 30, "taxa_divergencia": 5.0},
        json={"veredito": "aceitar", "autor": "a"},
    )

    assert r.status_code == 422


def test_estado_invalido_da_422():
    # `estado` era `str` solto: qualquer valor que não fosse exatamente
    # "pendente" — inclusive um typo como "pendentes" — virava silenciosamente
    # "decidida".
    r = cliente.get(
        "/api/fila/conciliacao",
        params={**PARAMS, "estado": "pendentes"},
    )

    assert r.status_code == 422


def test_estado_decidida_devolve_itens_decididos():
    # Sem cobertura nenhuma até aqui: o ramo `decididas()` e o caminho de
    # `_item` com decisão não-`None` nunca foram exercitados via HTTP.
    _grava_proposta("d-b-b00003", acao_sugerida="conciliar_com(l00003)")
    r = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params=PARAMS,
        json={"veredito": "aceitar", "autor": "controller@cliente"},
    )
    assert r.status_code == 200

    pendentes = cliente.get("/api/fila/conciliacao", params=PARAMS).json()
    assert pendentes["itens"] == []

    decididas = cliente.get(
        "/api/fila/conciliacao", params={**PARAMS, "estado": "decidida"}
    ).json()
    assert [i["divergence_id"] for i in decididas["itens"]] == ["d-b-b00003"]
    assert decididas["itens"][0]["decidido"] is True
    assert decididas["itens"][0]["veredito"] == "aceitar"


def test_resposta_da_decisao_aceita_reflete_veredito_e_lancamentos_por_lado():
    # Sem isto, trocar `descricao=e.account` por `descricao=e.supplier` em
    # `_do_contabil` (ou o equivalente do lado banco) passa a suíte inteira —
    # e é exatamente o que a Task 9 (tela da fila) vai renderizar.
    from orchestrator.synth.benchmark import build_benchmark

    ds = build_benchmark(seed=1, n=30, taxa_divergencia=0.15)
    banco = next(e for e in ds.bank if e.id == "b00003")
    contabil = next(e for e in ds.ledger if e.id == "l00003")

    _grava_proposta("d-b-b00003", acao_sugerida="conciliar_com(l00003)")

    corpo = cliente.post(
        "/api/fila/conciliacao/d-b-b00003/decisao",
        params=PARAMS,
        json={"veredito": "aceitar", "autor": "controller@cliente"},
    ).json()

    assert corpo["veredito"] == "aceitar"
    assert corpo["divergiu"] is False

    por_lado = {item["lado"]: item for item in corpo["lancamentos"]}
    assert por_lado["banco"]["descricao"] == banco.description
    assert por_lado["banco"]["contraparte"] == banco.counterparty
    assert por_lado["contabil"]["descricao"] == contabil.account
    assert por_lado["contabil"]["contraparte"] == contabil.supplier
