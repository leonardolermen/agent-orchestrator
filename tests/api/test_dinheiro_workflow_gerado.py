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


def test_executar_workflow_com_agente_responde_409(tmp_path):
    _gravar_pago(tmp_path)
    cliente = TestClient(app_mod.app)

    resposta = cliente.post(
        "/api/workflows/pago/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 60, "taxa_divergencia": 0.15}},
    )

    assert resposta.status_code == 409
    assert "CLI" in resposta.json()["detail"]


def test_o_modelo_nunca_e_chamado_por_um_endpoint(tmp_path, monkeypatch):
    # A outra metade: só o 409 passaria com a tranca quebrada. Espiona
    # `ClienteAusente.complete` e exige ZERO chamadas — se alguém um dia
    # trocar o sentinela por um cliente real, este teste é quem pega.
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
