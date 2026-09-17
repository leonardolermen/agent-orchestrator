"""O pool que transforma: um stage vê o que o anterior produziu.

Nenhum teste aqui menciona conciliação, e é o ponto — a mesma disciplina de
`tests/kernel/test_work.py`.
"""

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime.engine import execute


class Transformador:
    """Consome todo item de um kind e produz um de outro. Resolver de teste."""

    cost_class = CostClass.REGRA

    def __init__(self, name: str, de: str, para: str) -> None:
        self.name = name
        self._de = de
        self._para = para

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "teste")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        resolucoes, produzidos = [], []
        for item in work.of_kind(self._de):
            resolucoes.append(
                Resolution(
                    item_ids=frozenset({item.id}),
                    produced_by=self.name,
                    rule="transformou",
                )
            )
            produzidos.append(
                WorkItem(
                    id=f"{item.id}+{self._para}",
                    kind=self._para,
                    payload=f"{item.payload}/{self.name}",
                    origem=self.name,
                )
            )
        return ResolverOutput(
            resolutions=resolucoes, produced=tuple(produzidos), cost=Cost.zero()
        )


def test_produced_default_e_vazio():
    """Todo resolver de hoje devolve `ResolverOutput` sem `produced`. O default
    é o que mantém os 844 testes intocados."""
    assert ResolverOutput().produced == ()


def test_o_stage_seguinte_ve_o_que_o_anterior_produziu():
    """A asserção que não passava antes desta fatia: encadeamento por DADO.

    Sem `produced`, o stage 2 receberia só o que o stage 1 não resolveu — e o
    stage 1 resolveu tudo. O pipeline inteiro devolveria pool vazio.
    """
    d = WorkflowDefinition(
        id="pipeline",
        name="dois passos",
        stages=(
            Stage(name="um", cascade=(Transformador("um", "a", "b"),)),
            Stage(name="dois", cascade=(Transformador("dois", "b", "c"),)),
        ),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    r = execute(d, pool)

    # O item atravessou os dois degraus: a -> b -> c.
    assert [i.kind for i in r.unresolved.items] == ["c"]
    assert r.unresolved.items[0].payload == "x/um/dois"
    # Proveniência preservada em cada salto.
    assert r.unresolved.items[0].origem == "dois"
    # Duas resoluções: cada transformação CONSOME o item que leu.
    assert len(r.resolutions) == 2


def test_producao_nao_apaga_a_resolucao_que_a_acompanha():
    """Transformar É resolver: o item lido sai do pool pela porta de sempre."""
    d = WorkflowDefinition(
        id="um",
        name="um passo",
        stages=(Stage(name="um", cascade=(Transformador("um", "a", "b"),)),),
    )
    pool = WorkSet(items=(WorkItem(id="i", kind="a", payload="x"),))

    r = execute(d, pool)

    assert "i" not in r.unresolved.ids()
    assert r.resolutions[0].item_ids == frozenset({"i"})
