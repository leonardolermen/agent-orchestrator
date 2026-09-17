import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from orchestrator.api.app import app
from orchestrator.models import banco, conciliacao, contabil

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def _cache_limpo():
    """`executar()` delega para `_executar`, que é `lru_cache`d.

    Duas funções neste arquivo postam o EXATO mesmo corpo
    (`{"seed": 1, "n": 100, "taxa_divergencia": 0.15}`): o canário
    (`test_execucao_nao_chama_o_modelo_de_jeito_nenhum`) e
    `test_execucao_nao_serve_resolver_que_gasta_dinheiro`. Se uma rodar depois da
    outra com o cache ainda quente, a segunda vira cache hit — o corpo de
    `_executar` nem executa — e uma asserção sobre "o que foi
    chamado" passa vazia, sem ter provado nada. Hoje isso só não acontece por
    acidente de ordem no arquivo; `-k`, um teste novo inserido antes, ou um
    plugin de ordem aleatória destruiriam essa garantia em silêncio.
    """


def test_execucao_nao_chama_o_modelo_de_jeito_nenhum(monkeypatch):
    """A promessa do §5.2 do spec, virada teste — versão que de fato pina algo.

    A primeira versão deste teste levantava `AssertionError` de dentro de
    `AnthropicClient.complete` e checava só `status_code == 200`. Isso é
    vazio: `Investigator.investigar()` (ver `investigator.py`) envolve exatamente
    essa chamada num `try/except Exception` largo e PROPOSITAL — qualquer
    exceção vinda do modelo, canário incluído, vira uma abstenção silenciosa
    e a rota devolve 200 do mesmo jeito. Medido: liguei um `Investigator` de
    verdade na definição servida e o teste antigo continuou passando. Uma
    exceção que o próprio domínio existe para engolir não prova que nada foi
    chamado.

    Por isso o canário aqui NUNCA levanta. Ele grava a chamada numa lista e
    devolve uma resposta válida — e a asserção é sobre a lista, não sobre
    propagação. Não existe `except` que esconda um `append`.
    """

    chamadas: list[dict] = []

    def _espiao(self, system, messages, tools):
        chamadas.append({"system": system, "messages": messages, "tools": tools})
        from orchestrator.agent.llm import LLMResponse
        from orchestrator.kernel.cost import Cost

        return LLMResponse(text="{}", tool_calls=[], cost=Cost.zero())

    # Qualquer construção de cliente real passa por aqui.
    import orchestrator.agent.anthropic_client as ac

    monkeypatch.setattr(ac.AnthropicClient, "complete", _espiao)

    resposta = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 100, "taxa_divergencia": 0.15},
    )

    assert resposta.status_code == 200
    assert chamadas == []


def test_execucao_nao_serve_resolver_que_gasta_dinheiro():
    """Segunda perna da mesma garantia, sem monkeypatch nenhum.

    Pina a propriedade direto na saída do endpoint: nenhum resolver de
    `cost_class` AGENTE participou da execução. Isso pega até um agente que
    foi ligado mas ABSTEVE em toda divergência sem nunca chamar o modelo —
    caso que o espião do teste acima não pegaria, porque para ele nada de
    errado aconteceria (a lista de chamadas continuaria vazia mesmo com o
    agente presente). As duas asserções são independentes: uma pega quem
    chama o modelo, a outra pega quem foi apenas colocado na cascata.

    A asserção é "nenhum AGENTE", não "só REGRA": com o revisor (`HUMANO`) na
    definição padrão, a cascata já tem duas classes, e a propriedade que
    importa sempre foi "nada aqui gasta dinheiro" — nunca "só existem regras".
    """
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 100, "taxa_divergencia": 0.15},
    ).json()

    assert "AGENTE" not in [r["cost_class"] for r in corpo["by_resolver"]]


def test_execucao_reporta_taxa_e_custo_por_resolver():
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 0.15},
    ).json()

    nomes = [r["name"] for r in corpo["by_resolver"]]
    assert nomes == ["L1", "L2", "L3", "revisor"]
    assert all(r["microcents"] == 0 for r in corpo["by_resolver"])
    assert 0.80 < corpo["deterministic_rate"] < 0.95


def test_a_lacuna_e_reportada_explicitamente():
    # A definição padrão não tem agente. O que as regras não resolvem não
    # some do relatório: vira lacuna com tamanho. É o §3.4 do spec de
    # composição — o ponto mais valioso da tela.
    corpo = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 0.15},
    ).json()

    assert corpo["gap"]["items"] > 0
    soma = sum(r["rate"] for r in corpo["by_resolver"]) + corpo["gap"]["rate"]
    assert abs(soma - 1.0) < 1e-9


def test_n_invalido_da_422_em_vez_de_estourar():
    resposta = cliente.post(
        "/api/workflows/conciliacao/runs",
        json={"seed": 1, "n": 300, "taxa_divergencia": 5.0},
    )
    assert resposta.status_code == 422


def test_resolver_com_layer_diferente_do_name_e_reportado_pelo_proprio_nome(monkeypatch):
    """Pina P3.2 (DECISOES.md): `Resolver.name` é identidade, `Resolution.produced_by`
    é proveniência — dois conceitos que hoje coincidem para L1/L2/L3, mas não
    são o mesmo campo. Um resolver com `name` diferente do `layer` que ele
    estampa nas próprias resoluções ainda precisa aparecer com a contagem REAL na
    resposta do endpoint. Se o endpoint voltasse a ler `matches_by_layer`
    (proveniência) chaveado por `name` (identidade), este resolver reportaria
    0% mesmo tendo casado lançamentos de verdade — o defeito de zero silencioso
    que este teste existe para travar.
    """
    from orchestrator.kernel.cost import CostClass
    from orchestrator.kernel.definition import Stage, WorkflowDefinition
    from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput

    class _NomeDiferenteDaProveniencia:
        name = "resolver_x"
        cost_class = CostClass.REGRA

        def resolve(self, work):
            n = min(3, len(banco(work)), len(contabil(work)))
            return ResolverOutput(
                resolutions=[
                    conciliacao(
                        work,
                        frozenset({banco(work)[i].id, contabil(work)[i].id}),
                        # Proveniência deliberadamente != `name` acima.
                        produced_by="proveniencia_y",
                        rule="teste",
                    )
                    for i in range(n)
                ]
            )

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "name != layer, de propósito")

    def _fabrica(ctx):
        return WorkflowDefinition(
            id="layer_diferente",
            name="teste — name != layer",
            stages=(Stage(name="s", cascade=(_NomeDiferenteDaProveniencia(),)),),
        )

    # `registry()` monta um dict NOVO a cada chamada (embutida + disco); não
    # há mais um `_WORKFLOWS` mutável para `setitem`. Envolve a fábrica
    # original e acrescenta a entrada de teste por cima, preservando as
    # entradas reais (`conciliacao`).
    from orchestrator.workflows import registry as _registry_original

    def _registry_com_extra(raiz=None):
        fabricas = _registry_original(raiz)
        fabricas["layer_diferente"] = _fabrica
        return fabricas

    monkeypatch.setattr("orchestrator.api.app.registry", _registry_com_extra)

    corpo = cliente.post(
        "/api/workflows/layer_diferente/runs",
        json={"seed": 1, "n": 100, "taxa_divergencia": 0.15},
    ).json()

    (resolvido,) = corpo["by_resolver"]
    assert resolvido["name"] == "resolver_x"
    assert resolvido["matches"] == 3
    assert resolvido["rate"] == pytest.approx(3 / corpo["bank_total"])

    soma = sum(r["rate"] for r in corpo["by_resolver"]) + corpo["gap"]["rate"]
    assert soma == pytest.approx(1.0)


def test_pedido_SEM_fonte_continua_valendo():
    """A compatibilidade que mantém o canvas, a CLI do grill e os testes de
    hoje sem edição. O default é a sintética com os mesmos números."""
    from orchestrator.api.schemas import RunRequest

    r = RunRequest()

    assert r.fonte.tipo == "sintetica"
    assert (r.fonte.seed, r.fonte.n, r.fonte.taxa_divergencia) == (1, 300, 0.15)
    assert r.teto_microcents is None


def test_a_fonte_e_uma_UNIAO_DISCRIMINADA_por_tipo():
    """Um objeto com `seed?` ao lado de `caminho?` aceitaria os cruzamentos que
    não significam nada — uma fonte sintética com caminho, um arquivo com
    semente. `tipo` é o que torna os quatro cruzamentos dois."""
    from orchestrator.api.schemas import RunRequest

    r = RunRequest.model_validate(
        {"fonte": {"tipo": "arquivo", "caminho": "issues.csv",
                   "kind": "issue", "campo_id": "numero"}}
    )

    assert r.fonte.tipo == "arquivo"
    assert r.fonte.caminho == "issues.csv"
    assert not hasattr(r.fonte, "seed")


def test_fonte_de_arquivo_EXIGE_kind_e_campo_id():
    """Nenhum dos dois é inferível. `kind` é o que liga um degrau ao outro no
    grafo, e `campo_id` é o que dá identidade ao item — adivinhar qualquer um
    seria conveniência com cara de defeito."""
    import pydantic

    from orchestrator.api.schemas import RunRequest

    with pytest.raises(pydantic.ValidationError):
        RunRequest.model_validate({"fonte": {"tipo": "arquivo", "caminho": "x.csv"}})


def test_teto_negativo_e_recusado_pelo_SCHEMA():
    """Fora do handler, como `taxa_divergencia` já é: o FastAPI devolve 422
    sozinho em vez de deixar a aritmética de orçamento levantar mais fundo."""
    import pydantic

    from orchestrator.api.schemas import RunRequest

    with pytest.raises(pydantic.ValidationError):
        RunRequest(teto_microcents=-1)
