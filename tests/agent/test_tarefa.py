"""`Tarefa`: transforma item em item. Nunca propõe.

A simetria com `test_agent.py` é o ponto: `Agent` nunca devolve `resolutions`,
`Tarefa` nunca devolve `proposals`, e as duas rodam o mesmo laço.
"""

import pytest

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


def test_orcamento_total_interrompe_o_lote_sem_chamar_o_modelo():
    """Estourar o orçamento da EXECUÇÃO pula o resto do lote sem chamar o
    modelo — o mesmo teto de `Agent.resolve`, mas sem proposta a emitir: o
    item pulado simplesmente não resolve e fica no pool.

    `FakeLLMClient` só recebe UMA resposta preparada: se o laço tentasse
    chamar o modelo para o segundo ou o terceiro item, ele levantaria
    `AssertionError` sozinho — a asserção se auto-impõe.
    """
    pool = WorkSet(
        items=(
            WorkItem(id="i1", kind="achados", payload="a"),
            WorkItem(id="i2", kind="achados", payload="b"),
            WorkItem(id="i3", kind="achados", payload="c"),
        )
    )
    client = FakeLLMClient([_resposta("t1")])
    t = Tarefa(
        spec=_spec(budget_total_microcents=10_000),
        client=client,
        tools=ToolRegistry([]),
    )

    saida = t.resolve(pool)

    assert [r.item_ids for r in saida.resolutions] == [frozenset({"i1"})]
    assert len(client.chamadas) == 1


def test_resolver_sem_produzir_e_erro_alto():
    """A §3.1 exige a CONJUNÇÃO: consome A **e** produz B. Nada no tipo a impunha.

    Uma `Tarefa` de triagem que decide "isto é spam" e devolve
    `resolution=<x>, produced=()` faz o item sumir do run — sem produção, sem
    ninguém depois, e com `produz=frozenset()` a guarda de construção não tem o
    que checar. Erro de configuração, logo falha alto: abstenção é
    `resolution=None`, e as duas não podem ser confundíveis.
    """
    def _nao_produz(item_id, texto, custo, trace):
        return SaidaDaTarefa(
            cost=custo,
            trace=tuple(trace),
            resolution=Resolution(
                item_ids=frozenset({item_id}), produced_by="triador", rule="spam"
            ),
        )

    t = Tarefa(
        spec=_spec(transformar=_nao_produz),
        client=FakeLLMClient([_resposta("spam")]),
        tools=ToolRegistry([]),
    )

    with pytest.raises(ValueError, match="sem produzir nada"):
        t.resolve(_pool())


def test_resolver_ids_fora_do_item_recebido_e_erro_alto():
    """Uma `Tarefa` recebe UM item e resolve ESSE item.

    `WorkSet.without()` descarta qualquer id que receba, inclusive os que
    ninguém perguntou — então um `transformar` que alcança fora do seu mandato
    removeria três itens numa chamada de modelo, sem uma linha de erro.
    """
    def _come_demais(item_id, texto, custo, trace):
        return SaidaDaTarefa(
            cost=custo,
            trace=tuple(trace),
            resolution=Resolution(
                item_ids=frozenset({item_id, "outro"}),
                produced_by="escritor",
                rule="escreveu",
            ),
            produced=(WorkItem(id=f"{item_id}+r", kind="rascunho", payload=texto),),
        )

    t = Tarefa(
        spec=_spec(transformar=_come_demais),
        client=FakeLLMClient([_resposta("um texto")]),
        tools=ToolRegistry([]),
    )

    with pytest.raises(ValueError, match="ids fora do item que recebeu"):
        t.resolve(_pool())


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


def test_a_tarefa_DECLARA_o_que_consome_e_o_que_produz():
    """Sem isto, `consome_de`/`produz_de` derivam conjuntos VAZIOS para uma
    tarefa composta — e `consome` vazio significa "vejo o pool inteiro". O
    sintoma seria a composição passar na tela e a execução recusar com
    "produziu kind não declarado", sobre uma escolha que a tela acabou de
    aceitar: exatamente o defeito que `produz_de` foi escrita para matar.
    """
    from orchestrator.agent.declarado import TarefaDeclarada, construir_tarefa

    tarefa = construir_tarefa(
        TarefaDeclarada(
            name="escritor",
            system="escreva",
            kind="achados",
            produz="rascunho",
            prompt="{achados}",
        ),
        FakeLLMClient([_resposta("pronto")]),
    )

    d = tarefa.describe()

    assert d.consome == frozenset({"achados"})
    assert d.produz == frozenset({"rascunho"})


def test_uma_TarefaSpec_sem_kind_descreve_como_sempre():
    """Default vazio mantém a mudança retrocompatível: `domains/redacao` e
    qualquer spec escrita à mão continuam descrevendo o que descreviam."""
    tarefa = Tarefa(spec=_spec(), client=FakeLLMClient([]), tools=ToolRegistry([]))

    d = tarefa.describe()

    assert d.consome == frozenset()
    assert d.produz == frozenset()
