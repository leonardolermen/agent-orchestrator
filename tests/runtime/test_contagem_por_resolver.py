"""As DUAS contagens por resolver, e por que elas não são a mesma.

`resolved_by_resolver` conta RESOLUÇÕES; `resolved_items_by_resolver` conta os
ITENS que essas resoluções consumiram. Dividir a primeira pelo tamanho do pool
para produzir uma "taxa" é o erro de unidade que fez o canvas mostrar 42% onde
o trabalho tinha sido 84% — e é um erro que só aparece em domínio com mais de
um item por resolução, o que torna o teste abaixo a única testemunha.

Nenhum teste aqui menciona conciliação: a mesma disciplina de
`tests/runtime/test_producao.py`.
"""

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime.engine import execute


class _Casador:
    """Consome N itens por resolução. `n=1` é o domínio de um item por
    resolução, onde as duas contagens coincidem — e é por isso que ele não
    serve de testemunha sozinho."""

    cost_class = CostClass.REGRA

    def __init__(self, name: str, por_resolucao: int, quantas: int) -> None:
        self.name = name
        self._por = por_resolucao
        self._quantas = quantas

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "teste")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        ids = [i.id for i in work.items]
        lotes = [
            ids[k * self._por : (k + 1) * self._por] for k in range(self._quantas)
        ]
        return ResolverOutput(
            resolutions=[
                Resolution(item_ids=frozenset(lote), produced_by=self.name, rule="t")
                for lote in lotes
                if len(lote) == self._por
            ]
        )


def _pool(n: int) -> WorkSet:
    return WorkSet(items=tuple(WorkItem(id=f"i{k}", kind="x", payload={}) for k in range(n)))


def _definicao(*resolvers) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="t", name="t", stages=(Stage(name="s", cascade=tuple(resolvers)),)
    )


def test_as_duas_contagens_divergem_quando_uma_resolucao_consome_varios_itens():
    # 3 resoluções, 4 itens cada: 3 e 12, e o fator 4 é exatamente o que uma
    # taxa calculada com o número errado erraria.
    run = execute(_definicao(_Casador("r", por_resolucao=4, quantas=3)), _pool(20))

    assert run.resolved_by_resolver == {"r": 3}
    assert run.resolved_items_by_resolver == {"r": 12}
    assert len(run.unresolved.items) == 20 - 12


def test_a_contagem_de_itens_fecha_com_o_pool_que_sobrou():
    """A propriedade que o `/runs` publica como `sum(rate) + gap.rate == 1.0`,
    aqui sem HTTP: itens consumidos mais itens restantes é o pool."""
    run = execute(
        _definicao(
            _Casador("a", por_resolucao=2, quantas=3),
            _Casador("b", por_resolucao=3, quantas=2),
        ),
        _pool(20),
    )

    consumidos = sum(run.resolved_items_by_resolver.values())
    assert consumidos + len(run.unresolved.items) == 20


def test_um_resolver_que_nao_roda_nao_ganha_chave():
    """A mesma invariante de `cost_by_resolver`: a AUSÊNCIA da chave é o que
    diz "não rodou". Um zero fabricado diria "rodou e não achou nada"."""
    run = execute(_definicao(_Casador("r", por_resolucao=2, quantas=0)), _pool(4))

    # Rodou e não resolveu: a chave existe, com zero.
    assert run.resolved_items_by_resolver == {"r": 0}


class _Mentiroso:
    """Cita um id que não recebeu. Não é hipótese: `metrics.evaluate` já
    intersecta com o dataset real por causa desta possibilidade, e o
    docstring de lá diz `um resolver com bug — ou hostil`."""

    name = "mentiroso"
    cost_class = CostClass.REGRA

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "teste")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(
            resolutions=[
                Resolution(
                    item_ids=frozenset({"i0", "fantasma"}),
                    produced_by=self.name,
                    rule="t",
                )
            ]
        )


def test_a_contagem_de_itens_e_AFIRMADA_e_pode_passar_do_pool():
    """O limite declarado desta contagem, pinado em vez de suposto.

    `item_ids` é o que o resolver DIZ ter consumido; quem encolhe o pool é
    `WorkSet.without()`, que ignora id ausente. Um resolver que cita um id
    fantasma — ou dois resolvers do mesmo stage citando o mesmo item — fazem a
    soma por resolver passar do que de fato saiu do pool.

    Isto é deliberado e é a razão de a LACUNA sair de `unresolved` e não desta
    soma: o número que o operador lê nunca mente, e uma soma que estoura vira
    sintoma visível (`sum(rate) + gap.rate > 1.0`) em vez de lacuna negativa.
    """
    run = execute(_definicao(_Mentiroso()), _pool(4))

    # 2 itens AFIRMADOS, 1 item de fato consumido.
    assert run.resolved_items_by_resolver == {"mentiroso": 2}
    assert len(run.unresolved.items) == 3
    assert sum(run.resolved_items_by_resolver.values()) > 4 - len(run.unresolved.items)


def test_dois_resolvers_do_mesmo_stage_NAO_conseguem_citar_o_mesmo_item_honestamente():
    """O que protege a soma no caso normal, medido.

    O motor faz `work = work.without(saida.resolutions)` DEPOIS de cada
    resolver, dentro do laço do stage — então o segundo resolver recebe um pool
    do qual o que o primeiro consumiu já saiu. Um resolver que só cita o que
    recebeu não consegue colidir com o anterior. É disso que a soma depende, e
    não de uma guarda.
    """
    run = execute(
        _definicao(
            _Casador("a", por_resolucao=2, quantas=2),
            _Casador("b", por_resolucao=2, quantas=2),
        ),
        _pool(8),
    )

    assert run.resolved_items_by_resolver == {"a": 4, "b": 4}
    assert len(run.unresolved.items) == 0
