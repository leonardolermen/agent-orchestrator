"""Uma URL que dispara execução — e que gasta dinheiro.

O que estes testes protegem é o ACESSO. A execução em si tem os testes dela; o
que é novo aqui é que o mundo pode iniciá-la.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import orchestrator.api.app as api_app  # noqa: E402
from orchestrator.api import gatilhos  # noqa: E402
from orchestrator.api.app import app  # noqa: E402

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def _raiz_isolada(tmp_path, monkeypatch):
    """Gatilho gravado na raiz de verdade deixaria um SEGREDO utilizável no
    repositório de quem rodou a suíte."""
    monkeypatch.setattr(api_app, "_RAIZ_GATILHOS", tmp_path / "gatilhos")


def _workflow_autossuficiente(tmp_path, monkeypatch) -> str:
    """Um workflow com bloco `entrada` — o único tipo que aceita gatilho."""
    raiz = tmp_path / "composicoes"
    raiz.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", raiz)
    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    (raiz / "com-entrada.json").write_text(
        json.dumps(
            {
                "id": "com-entrada",
                "nome": "Com entrada",
                "justificativa": "",
                "gerado_em": datetime.now(UTC).isoformat(),
                "version": "x",
                "etapas": [
                    {
                        "nome": "ler",
                        "blocos": [
                            {
                                "tipo": "regra",
                                "nome": "entrada",
                                "parametros": {
                                    "tipo": "http",
                                    "kind": "pedido",
                                    "campo_id": "id",
                                    "url": "https://exemplo.invalido/api",
                                },
                            }
                        ],
                    },
                    {
                        "nome": "tratar",
                        "blocos": [
                            {
                                "tipo": "regra",
                                "nome": "filtro",
                                "parametros": {
                                    "kind": "pedido",
                                    "campo": "id",
                                    "teste": "preenchido",
                                },
                            }
                        ],
                    },
                ],
                "entrega": [],
                "max_rondas": 1,
            }
        ),
        encoding="utf-8",
    )
    return "com-entrada"


# --- criação ---------------------------------------------------------------


def test_criar_devolve_o_segredo_UMA_vez(tmp_path, monkeypatch):
    wid = _workflow_autossuficiente(tmp_path, monkeypatch)

    r = cliente.post("/api/triggers", json={"workflow_id": wid, "teto_microcents": 1000})

    assert r.status_code == 201, r.text
    assert r.json()["segredo"]
    # A LISTAGEM não carrega o segredo, e é o tipo da rota que garante isso.
    lista = cliente.get("/api/triggers").json()
    assert lista and "segredo" not in lista[0]


def test_o_segredo_NAO_e_gravado_em_claro(tmp_path, monkeypatch):
    """Um `data/` vazado não pode virar chave para gastar a conta de quem
    hospeda."""
    wid = _workflow_autossuficiente(tmp_path, monkeypatch)
    r = cliente.post("/api/triggers", json={"workflow_id": wid, "teto_microcents": 1000})
    segredo = r.json()["segredo"]

    gravado = (tmp_path / "gatilhos" / f"{r.json()['id']}.json").read_text(encoding="utf-8")

    assert segredo not in gravado
    assert "segredo_hash" in gravado


def test_workflow_SEM_entrada_e_recusado_na_CRIACAO(tmp_path, monkeypatch):
    """Um gatilho que existe, parece pronto e falha toda vez que alguém o chama
    é pior que um gatilho que não nasceu."""
    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", tmp_path / "vazio")
    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "vazio")

    r = cliente.post(
        "/api/triggers", json={"workflow_id": "conciliacao", "teto_microcents": 1000}
    )

    assert r.status_code == 422
    assert "não carrega a própria entrada" in r.json()["detail"]


def test_workflow_inexistente_e_404(tmp_path, monkeypatch):
    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", tmp_path / "vazio")
    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "vazio")

    r = cliente.post("/api/triggers", json={"workflow_id": "nao-existe", "teto_microcents": 1})

    assert r.status_code == 404


def test_teto_e_OBRIGATORIO(tmp_path, monkeypatch):
    """O disparo vem de fora e não é confiável: um teto que viesse nele seria um
    teto que quem dispara escolhe."""
    wid = _workflow_autossuficiente(tmp_path, monkeypatch)

    assert cliente.post("/api/triggers", json={"workflow_id": wid}).status_code == 422
    assert (
        cliente.post(
            "/api/triggers", json={"workflow_id": wid, "teto_microcents": 0}
        ).status_code
        == 422
    )


# --- disparo ---------------------------------------------------------------


def test_disparo_SEM_segredo_nao_executa(tmp_path, monkeypatch):
    wid = _workflow_autossuficiente(tmp_path, monkeypatch)
    gid = cliente.post(
        "/api/triggers", json={"workflow_id": wid, "teto_microcents": 1000}
    ).json()["id"]

    r = cliente.post(f"/api/triggers/{gid}/disparar")

    assert r.status_code == 404


def test_disparo_com_segredo_ERRADO_nao_executa(tmp_path, monkeypatch):
    wid = _workflow_autossuficiente(tmp_path, monkeypatch)
    gid = cliente.post(
        "/api/triggers", json={"workflow_id": wid, "teto_microcents": 1000}
    ).json()["id"]

    r = cliente.post(
        f"/api/triggers/{gid}/disparar", headers={"Authorization": "Bearer nao-e-esse"}
    )

    assert r.status_code == 404


def test_gatilho_inexistente_responde_IGUAL_a_segredo_errado(tmp_path, monkeypatch):
    """404 nos dois casos, e a mesma mensagem. Um 401 para "existe mas o segredo
    está errado" transformaria a rota num oráculo para descobrir ids válidos."""
    wid = _workflow_autossuficiente(tmp_path, monkeypatch)
    gid = cliente.post(
        "/api/triggers", json={"workflow_id": wid, "teto_microcents": 1000}
    ).json()["id"]

    inexistente = cliente.post("/api/triggers/nao-existe/disparar")
    errado = cliente.post(
        f"/api/triggers/{gid}/disparar", headers={"Authorization": "Bearer x"}
    )

    assert inexistente.status_code == errado.status_code == 404
    assert inexistente.json()["detail"] == errado.json()["detail"]


def test_revogar_APAGA_e_o_segredo_para_de_valer(tmp_path, monkeypatch):
    """Revogar é apagar e não marcar como inativo: a razão de revogar costuma
    ser que o segredo vazou."""
    wid = _workflow_autossuficiente(tmp_path, monkeypatch)
    criado = cliente.post(
        "/api/triggers", json={"workflow_id": wid, "teto_microcents": 1000}
    ).json()

    assert cliente.delete(f"/api/triggers/{criado['id']}").status_code == 204
    assert not (tmp_path / "gatilhos" / f"{criado['id']}.json").exists()
    assert (
        cliente.post(
            f"/api/triggers/{criado['id']}/disparar",
            headers={"Authorization": f"Bearer {criado['segredo']}"},
        ).status_code
        == 404
    )


# --- o modelo, sem HTTP ----------------------------------------------------


def test_autoriza_compara_em_tempo_constante(tmp_path):
    g, segredo = gatilhos.criar("w", 10, tmp_path)

    assert gatilhos.autoriza(g, segredo)
    assert not gatilhos.autoriza(g, segredo + "a")
    assert not gatilhos.autoriza(g, "")


def test_gatilho_sem_teto_e_recusado_no_MODELO(tmp_path):
    with pytest.raises(ValueError, match="sem teto"):
        gatilhos.Gatilho(
            id="g",
            workflow_id="w",
            teto_microcents=0,
            segredo_hash="x",
            criado_em=datetime.now(UTC),
        )


def test_ler_gatilho_inexistente_devolve_None(tmp_path: Path):
    assert gatilhos.ler("nao-existe", tmp_path) is None
