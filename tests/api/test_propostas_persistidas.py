"""A proposta do agente sobrevive ao run — ou o dinheiro vira um histograma.

Medido antes desta fatia: uma composição com agente rodava por `POST /runs`, o
modelo classificava cada item, e o que voltava era `propostas_por_tipo:
{"BUG": 2}`. A classificação, a explicação e a evidência não iam para lugar
nenhum: `gravar_proposta` tinha UM chamador em todo o `src/`, e era
`eval/agent_eval.py` — a avaliação offline. Pelo `/runs` a `Fila` era só LIDA
(o revisor precisa das decisões para existir), nunca escrita.

A consequência na tela: o agente roda, gasta, e a lacuna fica 100% sem que
ninguém possa ver o que ele propôs.
"""

import json

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
    return tmp_path


def _resposta(tipo: str = "BUG"):
    from orchestrator.agent.llm import LLMResponse
    from orchestrator.kernel.cost import Cost

    return LLMResponse(
        text=json.dumps(
            {"tipo": tipo, "explicacao": "o titulo diz que quebra",
             "evidencia": ["o titulo"], "confianca": "ALTA"}
        ),
        tool_calls=[],
        cost=Cost(input_tokens=100, output_tokens=50),
    )


def _cliente_falso(monkeypatch, respostas):
    import orchestrator.api.app as api_app
    from orchestrator.agent.llm import FakeLLMClient
    from orchestrator.agent.teto import ClienteComTeto, Orcamento

    fake = FakeLLMClient(list(respostas))
    def _de_execucao(teto):
        # A fábrica IGNORA o modelo: estes testes não são sobre qual modelo foi
        # chamado, e um fake por modelo faria o `chamadas` deles se espalhar.
        orcamento = Orcamento(teto)
        return (lambda _model: ClienteComTeto(fake, orcamento=orcamento)), orcamento

    monkeypatch.setattr(api_app, "_cliente_de_execucao", _de_execucao)
    return fake


def _csv_de_issues(tmp_path, monkeypatch, linhas: int = 2) -> None:
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir(exist_ok=True)
    corpo = "numero,titulo,corpo\n" + "".join(
        f"{i},titulo {i},corpo {i}\n" for i in range(1, linhas + 1)
    )
    (raiz / "issues.csv").write_text(corpo, encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)


_FONTE = {"tipo": "arquivo", "caminho": "issues.csv", "kind": "issue", "campo_id": "numero"}


def _compor(workflow_id: str) -> None:
    corpo = {
        "id": workflow_id,
        "nome": workflow_id,
        "blocos": [
            {
                "tipo": "agente",
                "declaracao": {
                    "name": "triador",
                    "system": "classifique",
                    "kind": "issue",
                    "prompt": "{titulo}",
                    "tipos": ["BUG", "FEATURE"],
                    "abstem_com": "NAO_SEI",
                    "ferramentas": [],
                    "max_turns": 1,
                    "budget_microcents": 4_000_000,
                },
            }
        ],
    }
    assert cliente.post("/api/composicoes", json=corpo).status_code == 201


def test_o_run_GRAVA_as_propostas_na_fila_do_conjunto(tmp_path, monkeypatch):
    """A trilha existe em disco depois do run, chaveada por `(workflow, ref)`.

    A asserção é sobre a `Fila` lida do zero — o mesmo caminho que o revisor
    usa — e não sobre a resposta HTTP: `propostas_por_tipo` já contava certo
    antes desta fatia, e contar não é guardar.
    """
    from orchestrator.review.fila import Fila, caminho_da_fila, dataset_de_ref

    _csv_de_issues(tmp_path, monkeypatch)
    _cliente_falso(monkeypatch, [_resposta("BUG"), _resposta("FEATURE")])
    _compor("triagem")

    r = cliente.post(
        "/api/workflows/triagem/runs",
        json={"fonte": _FONTE, "teto_microcents": 10_000_000},
    )
    assert r.status_code == 200, r.text

    ref = r.json()["input_ref"]
    fila = Fila(
        caminho_da_fila("triagem", dataset_de_ref(ref), raiz=tmp_path / "dados")
    )
    pendentes = fila.pendentes()

    assert [(p.item_id, p.tipo) for p in pendentes] == [("1", "BUG"), ("2", "FEATURE")]
    assert pendentes[0].explicacao == "o titulo diz que quebra"


def test_a_rota_de_PROPOSTAS_serve_qualquer_dominio(tmp_path, monkeypatch):
    """A leitura, sem vocabulário de conciliação.

    `GET /api/fila/{workflow_id}` não serve para isto e não é defeito dela: ela
    reconstrói o benchmark sintético para enriquecer cada item com lançamentos
    de banco e razão, e devolve `tipos` de `DivergenceType`. Sobre um CSV de
    issues não há lançamento nenhum para casar — a rota velha continua certa
    para a conciliação, e esta responde a outra pergunta: o que o agente propôs
    sobre os itens DESTE conjunto.

    Chaveada por `ref` e não por run: a fila é de `(workflow, conjunto)`, e o
    `ref` é o que a resposta do run já devolve.
    """
    _csv_de_issues(tmp_path, monkeypatch)
    _cliente_falso(monkeypatch, [_resposta("BUG"), _resposta("FEATURE")])
    _compor("triagem")

    run = cliente.post(
        "/api/workflows/triagem/runs",
        json={"fonte": _FONTE, "teto_microcents": 10_000_000},
    )
    assert run.status_code == 200, run.text

    r = cliente.get(
        "/api/fila/triagem/propostas", params={"ref": run.json()["input_ref"]}
    )

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert [(p["item_id"], p["tipo"]) for p in corpo] == [("1", "BUG"), ("2", "FEATURE")]
    assert corpo[0]["explicacao"] == "o titulo diz que quebra"
    assert corpo[0]["evidencia"] == ["o titulo"]
    assert corpo[0]["confianca"] == "ALTA"


def test_propostas_de_workflow_desconhecido_e_404(tmp_path, monkeypatch):
    """Mesma recusa de `GET /api/fila/{workflow_id}`: id que não existe no
    registro não devolve lista vazia, que leria como "esse workflow não propôs
    nada"."""
    r = cliente.get("/api/fila/nao-existe/propostas", params={"ref": "file:x@abc"})

    assert r.status_code == 404, r.text
    # O texto da guarda, não o "Not Found" genérico do roteador: sem esta
    # asserção o teste passaria com a rota INEXISTENTE, que é o estado em que
    # ele foi escrito.
    assert "nao-existe" in r.json()["detail"]
