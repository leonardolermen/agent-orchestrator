"""O quarto domínio: um pipeline, não um pool que encolhe.

Procurement e swe provaram que a cascata serve a mais de um domínio. Este prova
outra coisa: que ela serve a um trabalho que não tem "resolvido" no sentido de
conciliação — só tem "pronto". É o caso que a §0.1 do spec anterior recusava.
"""

from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.domains.redacao.workflow import Topico, definition, pool
from orchestrator.kernel.cost import Cost
from orchestrator.kernel.run import RunState
from orchestrator.runtime.engine import execute


def _resposta(texto: str) -> LLMResponse:
    return LLMResponse(text=texto, tool_calls=[], cost=Cost(input_tokens=10, output_tokens=5))


def test_o_topico_atravessa_os_tres_degraus():
    cliente = FakeLLMClient([_resposta("achei X"), _resposta("texto"), _resposta("texto revisado")])

    r = execute(definition(cliente), pool([Topico(id="t1", assunto="gatos")]))

    assert r.state is RunState.CONCLUIDO
    # O que sobra no pool É a entrega: kind terminal, declarado.
    assert [i.kind for i in r.unresolved.items] == ["texto_final"]
    assert r.unresolved.items[0].payload == "texto revisado"
    # Três transformações, uma por degrau.
    assert len(r.resolutions) == 3
    assert [x.produced_by for x in r.resolutions] == ["pesquisador", "escritor", "revisor"]


def test_a_proveniencia_sobrevive_aos_tres_saltos():
    """Sem `origem`, "de onde veio este texto" perde resposta no primeiro
    salto — e o replay não reconstrói o caminho."""
    cliente = FakeLLMClient([_resposta("a"), _resposta("b"), _resposta("c")])

    r = execute(definition(cliente), pool([Topico(id="t1", assunto="x")]))

    assert r.unresolved.items[0].origem == "revisor"


def test_o_custo_e_atribuido_por_degrau_nao_ao_sistema():
    """Custo por resolver é o que permite perguntar qual degrau é o caro — e
    é a pergunta que o laço de promoção vai responder depois."""
    cliente = FakeLLMClient([_resposta("a"), _resposta("b"), _resposta("c")])

    r = execute(definition(cliente), pool([Topico(id="t1", assunto="x")]))

    assert set(r.cost_by_resolver) == {"pesquisador", "escritor", "revisor"}
