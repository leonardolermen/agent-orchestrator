import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from orchestrator.api import app as app_mod
from orchestrator.grill.receita import Receita, ResolverReceita, para_json


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_RAIZ_FILA", tmp_path)
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    app_mod._executar_memoizado.cache_clear()
    yield
    app_mod._executar_memoizado.cache_clear()


def _gravar(tmp_path, id: str, *resolvers: str) -> None:
    r = Receita(
        id=id,
        nome=f"W {id}",
        justificativa="j",
        gerado_em=datetime(2026, 9, 15, tzinfo=UTC),
        resolvers=tuple(ResolverReceita(n, {}) for n in resolvers),
    )
    destino = tmp_path / "workflows"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / f"{id}.json").write_text(
        json.dumps(para_json(r), ensure_ascii=False), encoding="utf-8"
    )


def test_listar_inclui_a_embutida_e_as_geradas(tmp_path):
    _gravar(tmp_path, "acme", "L1", "revisor")
    cliente = TestClient(app_mod.app)

    dados = cliente.get("/api/workflows").json()

    ids = {x["id"] for x in dados}
    assert "conciliacao" in ids
    assert "acme" in ids


def test_workflow_gerado_tem_a_cascata_desenhavel(tmp_path):
    _gravar(tmp_path, "acme", "L1", "L2", "revisor")
    cliente = TestClient(app_mod.app)

    dados = cliente.get("/api/workflows/acme").json()

    # `stages[0]["cascade"]` é o caminho que a API de fato expõe (`WorkflowJSON`,
    # `schemas.py`) e que `web/canvas.js` de fato lê para desenhar a cascata —
    # não existe um campo `resolvers` paralelo no nível raiz.
    assert [r["name"] for r in dados["stages"][0]["cascade"]] == ["L1", "L2", "revisor"]


def test_workflow_gerado_executa_e_fecha_a_lacuna(tmp_path):
    _gravar(tmp_path, "acme", "L1", "revisor")
    cliente = TestClient(app_mod.app)

    dados = cliente.post(
        "/api/workflows/acme/runs", json={"seed": 1, "n": 60, "taxa_divergencia": 0.15}
    ).json()

    soma = sum(r["rate"] for r in dados["by_resolver"]) + dados["gap"]["rate"]
    assert soma == pytest.approx(1.0)


def test_workflow_com_agente_e_listado_como_nao_executavel(tmp_path):
    _gravar(tmp_path, "pago", "L1", "agente")
    cliente = TestClient(app_mod.app)

    dados = cliente.get("/api/workflows").json()
    pago = next(x for x in dados if x["id"] == "pago")

    assert pago["executavel"] is False
    assert "AGENTE" in pago["classes"]


def test_id_desconhecido_continua_404(tmp_path):
    cliente = TestClient(app_mod.app)
    assert cliente.get("/api/workflows/nao-existe").status_code == 404
