"""A cadeia escritor→revisor, montada por HTTP e MEDIDA.

É o §0 da spec invertido. Antes desta fatia, uma composição de duas etapas com
dois blocos de modelo fazia a etapa 2 receber os itens ORIGINAIS: medido, 4
chamadas sobre as mesmas issues, porque um agente declarado propõe e nunca
produz. Aqui o revisor precisa receber o texto do escritor.
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from orchestrator.api.app import app

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def _raizes_isoladas(tmp_path, monkeypatch):
    import orchestrator.api.app as api_app
    from orchestrator.authoring import composicao as composicao_mod

    monkeypatch.setattr(composicao_mod, "_RAIZ_PADRAO", tmp_path / "padrao-vazia")
    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", tmp_path / "composicoes")
    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    monkeypatch.setattr(api_app, "_RAIZ_FILA", tmp_path / "dados")
    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)
    raiz = tmp_path / "entradas"
    raiz.mkdir()
    (raiz / "issues.csv").write_text("numero,titulo\n1,login quebra\n", encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)


def _fake(monkeypatch, textos):
    import orchestrator.api.app as api_app
    from orchestrator.agent.llm import FakeLLMClient, LLMResponse
    from orchestrator.agent.teto import ClienteComTeto
    from orchestrator.kernel.cost import Cost

    fake = FakeLLMClient(
        [
            LLMResponse(text=t, tool_calls=[], cost=Cost(input_tokens=100, output_tokens=50))
            for t in textos
        ]
    )
    monkeypatch.setattr(
        api_app,
        "_cliente_de_execucao",
        lambda teto: ClienteComTeto(fake, teto_microcents=teto),
    )
    return fake


def _tarefa_json(nome, kind, produz, prompt):
    return {
        "tipo": "tarefa",
        "declaracao": {
            "name": nome,
            "system": "trabalhe o texto",
            "kind": kind,
            "produz": produz,
            "prompt": prompt,
            "ferramentas": [],
            "max_turns": 1,
            "budget_microcents": 4_000_000,
        },
    }


_FONTE = {"tipo": "arquivo", "caminho": "issues.csv", "kind": "issue", "campo_id": "numero"}


def _cadeia(workflow_id: str) -> dict:
    return {
        "id": workflow_id,
        "nome": "cadeia",
        "etapas": [
            {
                "nome": "escrever",
                "blocos": [
                    _tarefa_json("escritor", "issue", "rascunho", "Escreva sobre: {titulo}")
                ],
            },
            {
                "nome": "revisar",
                "blocos": [
                    _tarefa_json("revisor", "rascunho", "texto_final", "Revise: {rascunho}")
                ],
            },
        ],
        "entrega": ["texto_final"],
    }


def test_a_cadeia_escritor_revisor_MONTA_e_o_revisor_le_o_escritor(monkeypatch):
    fake = _fake(monkeypatch, ["rascunho do escritor", "versao revisada"])
    assert cliente.post("/api/composicoes", json=_cadeia("cadeia")).status_code == 201

    r = cliente.post(
        "/api/workflows/cadeia/runs",
        json={"fonte": _FONTE, "teto_microcents": 10_000_000},
    )

    assert r.status_code == 200, r.text
    # A prova: o prompt do SEGUNDO degrau carrega a saída do primeiro.
    assert fake.chamadas[-1]["messages"][0]["content"] == "Revise: rascunho do escritor"


def test_o_run_da_cadeia_RESOLVE_em_vez_de_so_propor(monkeypatch):
    """Um agente declarado propõe e o item fica no pool; uma tarefa resolve. É a
    diferença que o `por_resolver` do run mostra."""
    _fake(monkeypatch, ["rascunho do escritor", "versao revisada"])
    assert cliente.post("/api/composicoes", json=_cadeia("cadeia2")).status_code == 201

    r = cliente.post(
        "/api/workflows/cadeia2/runs",
        json={"fonte": _FONTE, "teto_microcents": 10_000_000},
    )

    corpo = r.json()
    por_nome = {p["name"]: p for p in corpo["por_resolver"]}
    assert por_nome["escritor"]["matches"] == 1
    assert por_nome["revisor"]["matches"] == 1
    assert corpo["propostas_por_tipo"] == {}


def test_produz_igual_ao_kind_vira_422_com_o_MOTIVO():
    """A recusa de domínio atravessa como 422 com o texto escrito para ser
    lido, não como "field required" do Pydantic."""
    corpo = {
        "id": "ruim",
        "nome": "ruim",
        "blocos": [_tarefa_json("ciclo", "issue", "issue", "{titulo}")],
    }

    r = cliente.post("/api/composicoes", json=corpo)

    assert r.status_code == 422, r.text
    assert "mesmo kind" in r.json()["detail"]
