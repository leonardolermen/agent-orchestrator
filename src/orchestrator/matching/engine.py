"""Orquestra as camadas determinísticas e apura o que sobrou.

Cada camada recebe apenas o que as anteriores não casaram. O que nenhuma
resolveu vira Divergence — e é isso, e só isso, que o agente de investigação
recebe. Ver spec 4.3.
"""

from dataclasses import dataclass, field
from typing import Protocol

from orchestrator.agent.proposal import Cost, InvestigationOutput, Proposal
from orchestrator.matching.exact import ExactMatcher
from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.matching.protocol import Matcher
from orchestrator.matching.tolerance import ToleranceMatcher
from orchestrator.models import BankEntry, Divergence, LedgerEntry, MatchResult


class Investigator(Protocol):
    """Quem investiga o que as camadas determinísticas não resolveram.

    Diferente de um Matcher: não resolve nada. Produz proposta, e o item
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


def default_matchers() -> list[Matcher]:
    """As três camadas, da mais barata para a mais cara."""
    return [ExactMatcher(), ToleranceMatcher(), GroupingMatcher()]


def reconcile(
    bank: list[BankEntry],
    ledger: list[LedgerEntry],
    matchers: list[Matcher] | None = None,
    investigator: Investigator | None = None,
) -> ReconcileResult:
    camadas = default_matchers() if matchers is None else matchers

    banco_restante = list(bank)
    contabil_restante = list(ledger)
    todos: list[MatchResult] = []

    for camada in camadas:
        resultados = camada.match(banco_restante, contabil_restante)
        if not resultados:
            continue

        todos.extend(resultados)
        casados_banco = {i for m in resultados for i in m.bank_ids}
        casados_contabil = {i for m in resultados for i in m.ledger_ids}
        banco_restante = [e for e in banco_restante if e.id not in casados_banco]
        contabil_restante = [e for e in contabil_restante if e.id not in casados_contabil]

    divergencias = [
        Divergence(id=f"d-b-{e.id}", bank_ids=frozenset({e.id}), ledger_ids=frozenset())
        for e in banco_restante
    ] + [
        Divergence(id=f"d-l-{e.id}", bank_ids=frozenset(), ledger_ids=frozenset({e.id}))
        for e in contabil_restante
    ]

    if investigator is None:
        return ReconcileResult(matches=todos, divergences=divergencias)

    # O investigador recebe SÓ o que sobrou, e o que ele devolve não remove
    # nada do pool: proposta não é resolução.
    saida = investigator.investigate(divergencias)
    return ReconcileResult(
        matches=todos,
        divergences=divergencias,
        proposals=saida.proposals,
        agent_cost=saida.cost,
    )
