"""O contrato único: regra, agente e humano com a mesma forma.

Antes deste módulo havia dois conceitos — `Matcher`, que casa, e
`Investigator`, que investiga — e por isso `reconcile` tinha dois parâmetros e
não havia cascata nenhuma no código. Ver o §1 do spec desta fatia.
"""

from dataclasses import dataclass, field
from typing import Protocol

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Proposal, Resolution
from orchestrator.kernel.work import WorkItem, WorkSet


@dataclass(frozen=True)
class ResolverOutput:
    """O que um resolver produziu.

    `resolutions` e `proposals` são campos separados, e é deliberado: uma
    resolução RESOLVE — sai do pool —, uma proposta apenas explica e o item
    continua em aberto até um humano aprovar. Unificar os dois num tipo só com
    um campo de status transformaria uma garantia de tipo numa convenção
    verificada, e um filtro esquecido viraria resolução fantasma.

    O campo chamava-se `matches` — palavra de conciliação. `resolutions` diz a
    mesma coisa sem supor que resolver seja casar.
    """

    resolutions: list[Resolution] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    # O que este resolver CRIOU. Campo separado de `resolutions` pela mesma
    # razão que `proposals` é separado: resolução consome, produção cria, e um
    # tipo único com campo de status transformaria duas garantias de tipo numa
    # convenção que alguém precisa verificar.
    #
    # `proposals` não aparece em nenhuma das duas expressões do motor
    # (`without` e `com`), e é essa ausência — agora que há DUAS maneiras de o
    # pool mudar — que mantém "proposta não resolve" estrutural.
    produced: tuple[WorkItem, ...] = ()
    cost: Cost = field(default_factory=Cost.zero)


@dataclass(frozen=True)
class ResolverDescription:
    """O que a API publica sobre um resolver. Dado, não comportamento."""

    name: str
    cost_class: CostClass
    summary: str


class Resolver(Protocol):
    """Uma tentativa de resolução dentro de uma cascata."""

    name: str
    cost_class: CostClass

    def resolve(self, work: WorkSet) -> ResolverOutput: ...

    def describe(self) -> ResolverDescription: ...
