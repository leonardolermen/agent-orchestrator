"""`Tarefa`: transforma item em item. Nunca propõe.

A simetria com `test_agent.py` é o ponto: `Agent` nunca devolve `resolutions`,
`Tarefa` nunca devolve `proposals`, e as duas rodam o mesmo laço.
"""

from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.agent.tarefa import SaidaDaTarefa, Tarefa, TarefaSpec
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.work import WorkItem, WorkSet


def _resposta(texto: str) -> LLMResponse:
    return LLMResponse(text=texto, tool_calls=[], cost=Cost(input_tokens=10, output_tokens=5))


def _transformar(item_id, texto, custo, trace):
    if not texto.strip():
        return None
    return SaidaDaTarefa(
        cost=custo,
        trace=tuple(trace),
        resolution=Resolution(
            item_ids=frozenset({item_id}), produced_by="escritor", rule="escreveu"
        ),
        produced=(
            WorkItem(id=f"{item_id}+r", kind="rascunho", payload=texto, origem="escritor"),
        ),
    )


def _spec(**kw) -> TarefaSpec:
    base = dict(
        name="escritor",
        system="escreva",
        model="claude-opus-5",
        prompt_de=lambda item: f"escreva sobre {item.payload}",
        transformar=_transformar,
    )
    return TarefaSpec(**{**base, **kw})


def _pool() -> WorkSet:
    return WorkSet(items=(WorkItem(id="i", kind="achados", payload="gatos"),))


def test_tarefa_resolve_e_produz():
    t = Tarefa(
        spec=_spec(), client=FakeLLMClient([_resposta("um texto")]),
        tools=ToolRegistry([]),
    )

    saida = t.resolve(_pool())

    assert [r.item_ids for r in saida.resolutions] == [frozenset({"i"})]
    assert [p.kind for p in saida.produced] == ["rascunho"]
    assert saida.produced[0].payload == "um texto"
    # A simetria com `Agent`: uma nunca propõe, a outra nunca resolve.
    assert saida.proposals == []


def test_tarefa_e_classe_agente():
    """Transformar custa uma chamada de modelo. A classe diz isso, e é o que
    põe a `Tarefa` no lugar certo da ordenação por custo."""
    t = Tarefa(spec=_spec(), client=FakeLLMClient([]), tools=ToolRegistry([]))

    assert t.cost_class is CostClass.AGENTE
    assert t.name == "escritor"


def test_desistir_deixa_o_item_no_pool_sem_resolver():
    """Falha após o retry NÃO resolve: o item fica para o próximo degrau.

    Um agente que estoura não derruba o run, e um item não some porque o
    modelo devolveu lixo — ele continua esperando alguém.
    """
    t = Tarefa(
        spec=_spec(max_format_retries=1),
        client=FakeLLMClient([_resposta(" "), _resposta(" ")]),
        tools=ToolRegistry([]),
    )

    saida = t.resolve(_pool())

    assert saida.resolutions == []
    assert saida.produced == ()
    # O custo dos turnos gastos é registrado mesmo sem resolver — senão a
    # cascata reportaria uma tentativa cara como se fosse de graça.
    assert saida.cost != Cost.zero()


def test_custo_de_varios_itens_e_somado():
    pool = WorkSet(
        items=(
            WorkItem(id="i1", kind="achados", payload="a"),
            WorkItem(id="i2", kind="achados", payload="b"),
        )
    )
    t = Tarefa(
        spec=_spec(),
        client=FakeLLMClient([_resposta("t1"), _resposta("t2")]),
        tools=ToolRegistry([]),
    )

    saida = t.resolve(pool)

    assert len(saida.resolutions) == 2
    assert saida.cost.output_tokens == 10
