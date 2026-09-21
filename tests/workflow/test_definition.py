import inspect

import pytest

from orchestrator.domains.reconciliation import default_definition
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet


def test_definicao_padrao_tem_as_tres_regras_num_stage():
    d = default_definition()

    assert d.id == "conciliacao"
    assert len(d.stages) == 1
    assert [r.name for r in d.stages[0].cascade] == ["L1", "L2", "L3", "revisor"]


def test_definicao_padrao_nao_gasta_dinheiro():
    # A propriedade que importa nunca foi "só existem regras" — foi "nada
    # aqui gasta dinheiro". Com o revisor na cascata a definição tem duas
    # classes, e trocar só a asserção sem trocar o nome transformaria um
    # guarda de dinheiro num guarda de forma.
    d = default_definition()

    classes = {r.cost_class for s in d.stages for r in s.cascade}
    assert CostClass.AGENTE not in classes


def test_definicao_padrao_inclui_o_revisor_por_ultimo():
    d = default_definition()

    cascata = d.stages[0].ordered()
    assert [r.name for r in cascata] == ["L1", "L2", "L3", "revisor"]
    assert cascata[-1].cost_class is CostClass.HUMANO


def test_definicao_padrao_sem_fila_nao_resolve_nada_pelo_revisor():
    # Sem fila, o revisor existe na cascata e é inerte. É isso que mantém a
    # CLI e o golden exatamente como estavam.
    from orchestrator.domains.reconciliation import reconcile
    from orchestrator.domains.reconciliation.synth.benchmark import build_benchmark
    from orchestrator.kernel.cost import CostClass as C

    ds = build_benchmark(seed=1, n=60, taxa_divergencia=0.15)
    r = reconcile(ds.bank, ds.ledger)

    assert r.matches_by_class.get(C.HUMANO, []) == []
    assert r.matches_by_resolver["revisor"] == 0


def test_a_fabrica_padrao_declara_o_parametro_fila():
    # `orchestrator.api.app._construir_definicao` decide se repassa a fila
    # olhando o NOME literal `fila` na assinatura desta função — não há
    # import nem type check que amarre os dois lados. Renomear este parâmetro
    # faz a suíte inteira continuar verde (nenhum teste chama
    # `default_definition` por nome de parâmetro) enquanto `/runs` volta a
    # servir sempre uma fila vazia, silenciosamente — o mesmo defeito que a
    # Task 8 corrigiu. Este teste existe só para travar esse nome.
    assert "fila" in inspect.signature(default_definition).parameters


def test_stage_expoe_a_cascata_ordenada_por_classe_de_custo():
    # A ordenação acontece por stage, não global: um stage posterior não pode
    # ter seus resolvers embaralhados com os de um anterior.
    d = default_definition()
    cascata = d.stages[0].ordered()

    assert [r.cost_class for r in cascata] == sorted(r.cost_class for r in cascata)


class _Nada:
    name = "nada"
    cost_class = CostClass.REGRA

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "teste")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput()


def _stage(nome, consome=frozenset(), produz=frozenset()):
    return Stage(name=nome, cascade=(_Nada(),), consome=consome, produz=produz)


def test_recusa_beco_sem_saida():
    """Um kind produzido que ninguém consome é item que fica no pool para
    sempre, sem nunca chegar ao degrau seguinte.

    O que esta guarda compra é reachability ESTÁTICA no grafo de kinds: o kind
    digitado errado e o esquecido são pegos na construção, e "isto é terminal"
    vira afirmação escrita. O que ela NÃO compra é humano — ver
    `tests/runtime/test_producao.py::test_a_guarda_nao_exige_humano`, que fixa
    a limitação, e o docstring de `agent/tarefa.py`, que a declara.
    """
    with pytest.raises(ValueError, match="beco sem saída"):
        WorkflowDefinition(
            id="w",
            name="w",
            stages=(_stage("um", consome=frozenset({"a"}), produz=frozenset({"b"})),),
        )


def test_entrega_declara_o_kind_terminal():
    """"Ninguém consome isto" tem de ser afirmação do autor, nunca acidente."""
    d = WorkflowDefinition(
        id="w",
        name="w",
        stages=(_stage("um", consome=frozenset({"a"}), produz=frozenset({"b"})),),
        entrega=frozenset({"b"}),
    )

    assert d.entrega == frozenset({"b"})


def test_kind_consumido_por_outro_stage_basta():
    d = WorkflowDefinition(
        id="w",
        name="w",
        stages=(
            _stage("um", consome=frozenset({"a"}), produz=frozenset({"b"})),
            _stage("dois", consome=frozenset({"b"}), produz=frozenset({"c"})),
        ),
        entrega=frozenset({"c"}),
    )

    assert len(d.stages) == 2


def test_stage_sem_consome_e_consumidor_curinga():
    """`consome` vazio é "vê o pool inteiro", não "não consome nada".

    A checagem literal lia o default como ausência de consumo e RECUSAVA este
    pipeline — correto, com o degrau de baixo no default — exigindo que o
    autor pusesse "b", um kind INTERMEDIÁRIO, em `entrega` só para construir.
    Isso fazia a declaração mentir E desligava a guarda justo para "b".

    O custo da correção está declarado no comentário de `__post_init__`: com um
    curinga no grafo, a guarda fica inerte para o grafo inteiro. Declarar
    `consome` em todos os stages é o que a compra de volta.
    """
    d = WorkflowDefinition(
        id="w",
        name="w",
        stages=(
            _stage("um", consome=frozenset({"a"}), produz=frozenset({"b"})),
            _stage("dois", produz=frozenset({"c"})),  # curinga: vê o pool inteiro
        ),
    )

    assert d.entrega == frozenset()


def test_max_rondas_menor_que_um_e_erro():
    """Zero ronda não executa nada e pareceria um workflow que não acha nada,
    em vez de configuração inválida — a mesma falha que `max_turns < 1` já
    recusa em `Agent`."""
    with pytest.raises(ValueError, match="max_rondas"):
        WorkflowDefinition(id="w", name="w", stages=(_stage("um"),), max_rondas=0)


def test_version_muda_com_consome_produz_e_max_rondas():
    """Dois grafos diferentes não podem hashear igual: `Run.workflow_version`
    é o que o benchmark usa para saber que comparou a mesma coisa."""
    base = WorkflowDefinition(
        id="w", name="w", stages=(_stage("um", produz=frozenset({"b"})),),
        entrega=frozenset({"b"}),
    )
    outro_consumo = WorkflowDefinition(
        id="w", name="w",
        stages=(_stage("um", consome=frozenset({"a"}), produz=frozenset({"b"})),),
        entrega=frozenset({"b"}),
    )
    mais_rondas = WorkflowDefinition(
        id="w", name="w", stages=(_stage("um", produz=frozenset({"b"})),),
        entrega=frozenset({"b"}), max_rondas=3,
    )

    assert base.version != outro_consumo.version
    assert base.version != mais_rondas.version
