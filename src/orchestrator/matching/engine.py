"""Orquestra a cascata de resolução e apura o que sobrou.

Cada resolver recebe apenas o que os anteriores não resolveram. O que nenhum
resolveu vira Divergence — e é isso, e só isso, que o agente de investigação
recebe. Ver spec 4.3.
"""

from dataclasses import dataclass, field
from typing import Protocol

from orchestrator.agent.proposal import Cost, InvestigationOutput, Proposal
from orchestrator.matching.exact import ExactMatcher
from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.matching.tolerance import ToleranceMatcher
from orchestrator.models import BankEntry, Divergence, LedgerEntry, MatchResult
from orchestrator.workflow.resolver import Resolver
from orchestrator.workflow.workset import WorkSet


class Investigator(Protocol):
    """Quem investiga o que a cascata determinística não resolveu.

    Diferente de um Resolver: não resolve nada. Produz proposta, e o item
    continua divergente até um humano aprovar.
    """

    name: str

    def investigate(self, divergences: list[Divergence]) -> InvestigationOutput: ...


@dataclass(frozen=True)
class ReconcileResult:
    matches: list[MatchResult]
    divergences: list[Divergence]
    proposals: list[Proposal] = field(default_factory=list)
    agent_cost: Cost = field(default_factory=Cost.zero)


def default_resolvers() -> list[Resolver]:
    """As três regras, da mais barata para a mais cara dentro da classe."""
    return [ExactMatcher(), ToleranceMatcher(), GroupingMatcher()]


def reconcile(
    bank: list[BankEntry],
    ledger: list[LedgerEntry],
    resolvers: list[Resolver] | None = None,
    investigator: Investigator | None = None,
) -> ReconcileResult:
    cascata = default_resolvers() if resolvers is None else resolvers
    work = WorkSet(bank=list(bank), ledger=list(ledger))
    todos: list[MatchResult] = []
    propostas: list[Proposal] = []

    # `sorted` é estável: entre classes a ordem é derivada, dentro da classe a
    # ordem que veio na lista sobrevive. Uma linha entrega as duas regras.
    for resolver in sorted(cascata, key=lambda r: r.cost_class):
        saida = resolver.resolve(work)
        todos.extend(saida.matches)
        propostas.extend(saida.proposals)
        # Só `matches` encolhe o pool. `saida.proposals` não aparece aqui, e
        # é essa ausência que torna a invariante estrutural.
        work = work.without(saida.matches)

    divergencias = work.as_divergences()

    if investigator is None:
        return ReconcileResult(
            matches=todos, divergences=divergencias, proposals=propostas
        )

    saida_agente = investigator.investigate(divergencias)
    return ReconcileResult(
        matches=todos,
        divergences=divergencias,
        proposals=[*propostas, *saida_agente.proposals],
        agent_cost=saida_agente.cost,
    )
