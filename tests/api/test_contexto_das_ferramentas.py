"""A borda liga as ferramentas aos DADOS — ou o agente gasta pedindo o que ninguém executa.

Medido antes desta fatia, pelo caminho que a tela usa: uma composição com um
agente que declara `contar_palavras`, rodando por `POST /runs`, fazia o modelo
pedir a ferramenta e recebia de volta

    {"erro": "registro não ligado a dados: este é o catálogo do domínio,
     não um registro executável. use `com_contexto(...)`"}

O run respondia 200, `falhas: 0`, e a conta vinha. É o "não achei nada
indistinguível de não procurei" que `ToolRegistry.call` já recusa em voz alta
um nível abaixo — só que ninguém ouvia, porque `_de_composicao` construía a
cascata sem contexto nenhum e `call` nunca levanta.

Os dois testes deste arquivo são as duas metades da mesma frase, e o segundo
existe porque o primeiro sozinho seria satisfeito por um contexto VAZIO —
trocar "não ligado" por "ligado a nada" é o mesmo defeito com roupa melhor.
"""

import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from orchestrator.api.app import app

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def _raizes_isoladas(tmp_path, monkeypatch):
    """Nenhuma raiz de verdade: `gravar` escreve, e um run persiste."""
    import orchestrator.api.app as api_app
    from orchestrator.authoring import composicao as composicao_mod

    monkeypatch.setattr(composicao_mod, "_RAIZ_PADRAO", tmp_path / "padrao-vazia")
    monkeypatch.setattr(api_app, "_RAIZ_COMPOSICOES", tmp_path / "composicoes")
    monkeypatch.setattr(api_app, "_RAIZ_RECEITAS", tmp_path / "receitas")
    monkeypatch.setattr(api_app, "_RAIZ_FILA", tmp_path / "dados")
    monkeypatch.setattr(api_app, "_tem_chave", lambda: True)


def _declaracao(nome: str, kind: str, prompt: str, ferramentas: list[str]) -> dict:
    return {
        "name": nome,
        "system": "classifique",
        "kind": kind,
        "prompt": prompt,
        "tipos": ["BUG", "FEATURE"],
        "abstem_com": "NAO_SEI",
        "ferramentas": ferramentas,
        "max_turns": 3,
        "budget_microcents": 4_000_000,
    }


def _pede(nome: str, argumentos: dict):
    from orchestrator.agent.llm import LLMResponse, ToolCall
    from orchestrator.kernel.cost import Cost

    return LLMResponse(
        text="vou olhar",
        tool_calls=[ToolCall(id="t1", name=nome, arguments=argumentos)],
        cost=Cost(input_tokens=10, output_tokens=5),
    )


def _responde(tipo: str = "BUG"):
    from orchestrator.agent.llm import LLMResponse
    from orchestrator.kernel.cost import Cost

    return LLMResponse(
        text=json.dumps(
            {"tipo": tipo, "explicacao": "porque sim", "evidencia": ["o titulo"],
             "confianca": "ALTA"}
        ),
        tool_calls=[],
        cost=Cost(input_tokens=100, output_tokens=50),
    )


def _cliente_falso(monkeypatch, respostas):
    """Troca só a ponta de rede, como `test_execucao._cliente_falso`: o embrulho
    de teto REAL continua no caminho, e com o teto REAL do pedido."""
    import orchestrator.api.app as api_app
    from orchestrator.agent.llm import FakeLLMClient
    from orchestrator.agent.teto import ClienteComTeto

    fake = FakeLLMClient(list(respostas))
    monkeypatch.setattr(
        api_app,
        "_cliente_de_execucao",
        lambda teto: ClienteComTeto(fake, teto_microcents=teto),
    )
    return fake


def _resultados_de_ferramenta(fake) -> list[dict]:
    """O que o modelo RECEBEU de volta de cada ferramenta que pediu.

    A asserção é sobre isto e não sobre o corpo do run de propósito: `call`
    nunca levanta e `conversa.py` engole exceção do modelo, então um erro de
    ferramenta não aparece em `falhas` nem muda o status — foi exatamente assim
    que a lacuna sobreviveu a uma suíte verde. O único lugar onde ela é visível
    é o turno seguinte da conversa.

    Só a ÚLTIMA chamada, e não a varredura de todas: `FakeLLMClient` guarda a
    lista de `messages` por REFERÊNCIA, e `conversar` a muta a cada turno — de
    modo que toda entrada de `chamadas` mostra o histórico FINAL. Varrer as
    duas contava o mesmo `tool_result` duas vezes, e uma asserção sobre a
    contagem passaria a medir o fake em vez do código.
    """
    saida = []
    for msg in fake.chamadas[-1].get("messages", []):
        conteudo = msg.get("content")
        if not isinstance(conteudo, list):
            continue
        for bloco in conteudo:
            if isinstance(bloco, dict) and bloco.get("type") == "tool_result":
                saida.append(json.loads(bloco["content"]))
    return saida


def _csv_de_issues(tmp_path, monkeypatch, linhas: int = 1) -> None:
    import orchestrator.api.app as api_app

    raiz = tmp_path / "entradas"
    raiz.mkdir(exist_ok=True)
    corpo = "numero,titulo,corpo\n" + "".join(
        f"{i},titulo {i},corpo com quatro palavras\n" for i in range(1, linhas + 1)
    )
    (raiz / "issues.csv").write_text(corpo, encoding="utf-8")
    monkeypatch.setattr(api_app, "_RAIZ_ENTRADAS", raiz)


_FONTE_ISSUES = {
    "tipo": "arquivo",
    "caminho": "issues.csv",
    "kind": "issue",
    "campo_id": "numero",
}


def test_ferramenta_de_agente_COMPOSTO_executa_em_vez_de_recusar(tmp_path, monkeypatch):
    """A metade genérica: uma ferramenta que não precisa de dado nenhum
    (`contar_palavras`) precisa RODAR num run de composição."""
    _csv_de_issues(tmp_path, monkeypatch)
    fake = _cliente_falso(
        monkeypatch, [_pede("contar_palavras", {"texto": "uma duas tres"}), _responde()]
    )
    corpo = {
        "id": "com-ferramenta",
        "nome": "com ferramenta",
        "blocos": [
            {
                "tipo": "agente",
                "declaracao": _declaracao(
                    "pesquisador", "issue", "{titulo}", ["contar_palavras"]
                ),
            }
        ],
    }
    assert cliente.post("/api/composicoes", json=corpo).status_code == 201

    r = cliente.post(
        "/api/workflows/com-ferramenta/runs",
        json={"fonte": _FONTE_ISSUES, "teto_microcents": 10_000_000},
    )

    assert r.status_code == 200, r.text
    resultados = _resultados_de_ferramenta(fake)
    assert resultados == [{"palavras": 3}], resultados


def test_ferramenta_de_CONCILIACAO_enxerga_o_pool_que_vai_rodar(monkeypatch):
    """A outra metade: ligar o registro a um contexto VAZIO passaria no teste de
    cima e seria o mesmo defeito com roupa melhor.

    `buscar_lancamentos` sobre `ctx.ledger == []` devolve `[]` — e uma lista
    vazia é a resposta legítima de "não existe lançamento com esse documento".
    O modelo não tem como distinguir as duas, gasta o turno seguinte
    concluindo do vazio, e a conta vem igual. Por isso a asserção é sobre um
    documento que SABIDAMENTE está no pool: ele só pode voltar se o contexto
    for o do run.
    """
    from orchestrator.domains.reconciliation.synth.benchmark import build_benchmark

    ds = build_benchmark(seed=1, n=5, taxa_divergencia=0.15)
    documento = ds.ledger[0].document

    fake = _cliente_falso(
        monkeypatch,
        [_pede("buscar_lancamentos", {"documento": documento}), _responde()] * 20,
    )
    corpo = {
        "id": "conciliador",
        "nome": "conciliador",
        "blocos": [
            {
                "tipo": "agente",
                "declaracao": _declaracao(
                    "auditor", "contabil", "{document}", ["buscar_lancamentos"]
                ),
            }
        ],
    }
    assert cliente.post("/api/composicoes", json=corpo).status_code == 201

    r = cliente.post(
        "/api/workflows/conciliador/runs",
        json={
            "fonte": {"tipo": "sintetica", "seed": 1, "n": 5, "taxa_divergencia": 0.15},
            "teto_microcents": 50_000_000,
        },
    )

    assert r.status_code == 200, r.text
    resultados = _resultados_de_ferramenta(fake)
    assert resultados, "o modelo não recebeu resultado de ferramenta nenhum"
    assert [le["documento"] for le in resultados[0]] == [documento], resultados
