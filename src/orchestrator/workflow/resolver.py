"""O contrato único: regra, agente e humano com a mesma forma.

Antes deste módulo havia dois conceitos — `Matcher`, que casa, e
`Investigator`, que investiga — e por isso `reconcile` tinha dois parâmetros e
não havia cascata nenhuma no código. Ver o §1 do spec desta fatia.
"""

from dataclasses import dataclass, field
from typing import Protocol

from orchestrator.agent.proposal import Proposal
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.models import MatchResult
from orchestrator.workflow.workset import WorkSet


@dataclass(frozen=True)
class ResolverOutput:
    """O que um resolver produziu.

    `matches` e `proposals` são campos separados, e é deliberado: um match
    RESOLVE — sai do pool —, uma proposta apenas explica e o item continua
    divergente até um humano aprovar. Unificar os dois num tipo só com um
    campo de status transformaria uma garantia de tipo numa convenção
    verificada, e um filtro esquecido viraria conciliação fantasma.
    """

    matches: list[MatchResult] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
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
