"""Software Engineering: "que mudança esta issue pede?"

O CASO DEGENERADO do spec de composição §1.3 — uma cascata **sem nenhum
resolver de classe REGRA**. Não há regra barata que leia uma issue; vai direto
ao agente, e o humano fecha.

Existe para ser o teste mais duro da abstração, não para ser útil. Se o kernel
só souber expressar cascatas que começam com regra, ele não é genérico — é a
conciliação com nomes trocados.

O que ele exercita e nenhum outro domínio exercita:
  - `Stage.ordered()` com uma classe só;
  - `matches_by_class` SEM a chave `REGRA` (a guarda que `metrics` documenta e
    que nunca tinha sido exercida por um domínio real);
  - `WorkSet` de um `kind` só, onde a assimetria da conciliação não existe.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Confidence, Proposal
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet

ISSUE = "issue"


@dataclass(frozen=True)
class Issue:
    """O payload. Congelado, como todo payload de domínio."""

    id: str
    titulo: str
    corpo: str


def pool(issues: list[Issue]) -> WorkSet:
    return WorkSet(items=tuple(WorkItem(id=i.id, kind=ISSUE, payload=i) for i in issues))


@dataclass
class Triador:
    """Classifica a issue. Classe AGENTE, mas sem chamar modelo nenhum.

    É um esqueleto: ele não é um agente de verdade, e dizer que é seria mentir.
    O que ele exercita é a FORMA — um resolver de classe paga que devolve
    `proposals` e nunca `resolutions`, porque proposta não resolve.
    """

    name: str = field(default="triador", init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "classifica a issue")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(
            proposals=[
                Proposal(
                    item_id=i.id,
                    kind="BUG" if "erro" in i.payload.titulo.lower() else "FEATURE",
                    explanation=f"pelo título: {i.payload.titulo!r}",
                    evidence=(f"issue {i.id}",),
                    confidence=Confidence.BAIXA,
                    suggested_action="revisar_manual",
                )
                for i in work.of_kind(ISSUE)
            ],
            cost=Cost.zero(),
        )


def definition() -> WorkflowDefinition:
    """Sem `REGRA`. É o ponto."""
    return WorkflowDefinition(
        id="swe",
        name="Triagem de issue",
        stages=(Stage(name="que mudança esta issue pede?", cascade=(Triador(),)),),
    )
