import json
from datetime import UTC, datetime

import pytest

# `api` é extra opcional (`pyproject.toml`). Sem a guarda, este arquivo
# derruba a COLETA da suíte inteira numa instalação `[dev]` — não só os
# próprios testes. Ver `.github/workflows/ci.yml`, que roda as duas variantes.
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.api import app as app_mod
from orchestrator.grill.receita import Receita, ResolverReceita, para_json


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_RAIZ_FILA", tmp_path)
    monkeypatch.setattr(app_mod, "_RAIZ_RECEITAS", tmp_path)
    # Também a raiz de COMPOSIÇÕES: sem ela, `registry()` cai em
    # `data/composicoes` do desenvolvedor, e a primeira composição salva pela
    # tela deixava `test_receita_inconstruivel_nao_derruba_a_listagem` vermelho
    # por um motivo que nada tem a ver com o que ele afirma.
    monkeypatch.setattr(app_mod, "_RAIZ_COMPOSICOES", tmp_path / "composicoes")
    yield


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
        "/api/workflows/acme/runs",
        json={"fonte": {"tipo": "sintetica", "seed": 1, "n": 60, "taxa_divergencia": 0.15}},
    ).json()

    soma = sum(r["rate"] for r in dados["por_resolver"]) + dados["gap"]["rate"]
    assert soma == pytest.approx(1.0)
    # Em itens absolutos, a mesma afirmação sem as divisões.
    assert dados["resolvidos"] + dados["gap"]["items"] == dados["itens"]
    assert [r["name"] for r in dados["por_resolver"]] == ["L1", "revisor"]


def test_workflow_com_agente_e_executavel_conforme_a_CHAVE(tmp_path, monkeypatch):
    """`executavel` responde "o botão Run vai funcionar?", e a resposta mudou.

    Era "a cascata não tem AGENTE", porque `/runs` recusava toda cascata paga.
    Com o caminho pago aberto, uma cascata com agente roda num servidor que tem
    `ANTHROPIC_API_KEY` e é recusada com 409 num que não tem — então é a chave
    que decide, e a listagem tem de dizer o mesmo que a rota diria.

    Monkeypatch dos DOIS lados de propósito: sem isso o teste passaria ou
    falharia conforme a variável de ambiente da máquina que o roda, que é
    exatamente a classe de teste que esta fatia existe para não deixar em pé.

    "investigador", não "agente": o catálogo plano (Task 3) nomeia o bloco
    AGENTE da conciliação pelo `Resolver.name` que ele sempre teve — o
    cardápio do grill é que usava a chave "agente" só para propor este
    mesmo bloco.
    """
    _gravar(tmp_path, "pago", "L1", "investigador")
    cliente = TestClient(app_mod.app)

    def _pago():
        return next(x for x in cliente.get("/api/workflows").json() if x["id"] == "pago")

    monkeypatch.setattr(app_mod, "_tem_chave", lambda: False)
    sem = _pago()
    monkeypatch.setattr(app_mod, "_tem_chave", lambda: True)
    com = _pago()

    assert sem["executavel"] is False
    assert com["executavel"] is True
    assert "AGENTE" in sem["classes"] == com["classes"]


def test_receita_inconstruivel_nao_derruba_a_listagem(tmp_path, capsys):
    # Gatilho realista: o catálogo é feito para CRESCER, e renomear um
    # parâmetro (ou aposentar um resolver) invalida receitas já gravadas. Uma
    # receita que PARSEIA mas não CONSTRÓI derrubava `GET /api/workflows` com
    # 500 — e com ele o seletor do canvas para TODOS os workflows, enquanto
    # cada um deles, individualmente, continuava respondendo 200.
    # `listar_receitas` já isola o parse; esta é a outra metade.
    _gravar(tmp_path, "acme", "L1", "revisor")
    _gravar(tmp_path, "quebrada", "L9")
    cliente = TestClient(app_mod.app)

    resposta = cliente.get("/api/workflows")

    assert resposta.status_code == 200
    assert {x["id"] for x in resposta.json()} == {"conciliacao", "acme"}
    # Pular não pode ser sumir em silêncio — a mesma frase que
    # `listar_receitas` já escreve para o arquivo ilegível.
    assert "quebrada" in capsys.readouterr().err


def test_conciliacao_no_disco_nao_substitui_a_embutida(tmp_path):
    # A segunda tranca de `_fabricas`: `conciliacao` é id reservado no
    # registro, mas nada impede um arquivo posto à mão no disco. Se a ordem do
    # dict deixasse o disco vencer, o golden e o demo inteiro passariam a
    # descrever outra coisa sem que nenhum teste percebesse.
    _gravar(tmp_path, "conciliacao", "L1")
    cliente = TestClient(app_mod.app)

    dados = cliente.get("/api/workflows/conciliacao").json()

    assert dados["name"] == "Conciliação bancária"
    assert [r["name"] for r in dados["stages"][0]["cascade"]] == ["L1", "L2", "L3", "revisor"]
    # E a listagem descreve a MESMA definição embutida, não a do arquivo
    # (cujo `nome` seria "W conciliacao"), nem uma entrada duplicada.
    resumos = [x for x in cliente.get("/api/workflows").json() if x["id"] == "conciliacao"]
    assert [x["nome"] for x in resumos] == ["Conciliação bancária"]


def test_id_desconhecido_continua_404(tmp_path):
    cliente = TestClient(app_mod.app)
    assert cliente.get("/api/workflows/nao-existe").status_code == 404
