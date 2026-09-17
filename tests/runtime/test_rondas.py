"""O laço até ponto fixo: aresta de volta, e o teto que a torna segura."""

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.run import RunState
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime.engine import execute


class PingPong:
    """Troca `a` por `b` e `b` por `a`, para sempre. Um laço que não converge."""

    cost_class = CostClass.REGRA

    def __init__(self, name: str, de: str, para: str) -> None:
        self.name, self._de, self._para = name, de, para

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "teste")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        res, prod = [], []
        for i, item in enumerate(work.of_kind(self._de)):
            res.append(
                Resolution(
                    item_ids=frozenset({item.id}), produced_by=self.name, rule="pingpong"
                )
            )
            prod.append(
                WorkItem(
                    id=f"{item.id}-{self.name}-{i}",
                    kind=self._para,
                    payload=item.payload,
                    origem=self.name,
                )
            )
        return ResolverOutput(resolutions=res, produced=tuple(prod), cost=Cost.zero())


def _pingpong(max_rondas: int) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="pingpong",
        name="pingpong",
        stages=(
            Stage(
                name="ida",
                cascade=(PingPong("ida", "a", "b"),),
                consome=frozenset({"a"}),
                produz=frozenset({"b"}),
            ),
            Stage(
                name="volta",
                cascade=(PingPong("volta", "b", "a"),),
                consome=frozenset({"b"}),
                produz=frozenset({"a"}),
            ),
        ),
        max_rondas=max_rondas,
    )


def test_max_rondas_1_e_exatamente_a_semantica_de_hoje():
    """Uma passada pelos stages, em ordem. O default não muda nada."""
    r = execute(_pingpong(1), WorkSet(items=(WorkItem(id="i", kind="a", payload=1),)))

    assert r.rondas == 1
    assert r.state is RunState.CONCLUIDO
    # ida (a->b) e volta (b->a) rodaram uma vez cada, na mesma ronda.
    assert len(r.resolutions) == 2


def test_bater_o_teto_e_estado_explicito_nunca_silencio():
    """Um run que parou por teto NÃO terminou, e tem de dizer isso.

    Terminar como CONCLUIDO seria a mesma desonestidade que imprimir 100% de
    precisão sobre dois itens — o repositório já revogou duas conclusões por
    isso.
    """
    r = execute(_pingpong(3), WorkSet(items=(WorkItem(id="i", kind="a", payload=1),)))

    assert r.rondas == 3
    assert r.state is RunState.LIMITE_DE_RONDAS


def test_o_laco_para_sozinho_quando_a_ronda_nao_faz_nada():
    """Ponto fixo: sem resolução e sem produção, não há por que rodar de novo.

    O teto alto prova que quem parou o laço foi a convergência, não ele.
    """
    d = WorkflowDefinition(
        id="parado",
        name="parado",
        stages=(
            Stage(
                name="ida",
                cascade=(PingPong("ida", "a", "b"),),
                consome=frozenset({"a"}),
                produz=frozenset({"b"}),
            ),
        ),
        entrega=frozenset({"b"}),
        max_rondas=50,
    )

    r = execute(d, WorkSet(items=(WorkItem(id="i", kind="a", payload=1),)))

    # Ronda 1 transformou; ronda 2 não achou mais nada de kind "a" e parou.
    assert r.rondas == 2
    assert r.state is RunState.CONCLUIDO
    assert len(r.resolutions) == 1
