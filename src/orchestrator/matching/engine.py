"""Orquestra a cascata de resolução e apura o que sobrou.

Cada resolver recebe apenas o que os anteriores não resolveram. O que nenhum
resolveu vira Divergence — e é isso, e só isso, que o agente de investigação
recebe. Ver spec 4.3.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orchestrator.agent.proposal import Cost, Proposal
from orchestrator.matching.exact import ExactMatcher
from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.matching.tolerance import ToleranceMatcher
from orchestrator.models import BankEntry, Divergence, LedgerEntry, MatchResult
from orchestrator.workflow.resolver import Resolver
from orchestrator.workflow.workset import WorkSet

if TYPE_CHECKING:
    # Só para o type checker: em tempo de execução este import viraria
    # circular (`definition.py` importa `default_resolvers` deste módulo). O
    # import de verdade, usado dentro de `reconcile`, é local de propósito.
    from orchestrator.workflow.definition import WorkflowDefinition


@dataclass(frozen=True)
class ReconcileResult:
    matches: list[MatchResult]
    divergences: list[Divergence]
    proposals: list[Proposal] = field(default_factory=list)
    # Custo por resolver, não do sistema. Um resolver que rodou e não custou
    # nada aparece com Cost.zero(); um que não rodou não aparece. A diferença
    # importa na tela: "de graça" e "não rodou" são coisas diferentes.
    cost_by_resolver: dict[str, Cost] = field(default_factory=dict)


def default_resolvers() -> list[Resolver]:
    """As três regras, da mais barata para a mais cara dentro da classe."""
    return [ExactMatcher(), ToleranceMatcher(), GroupingMatcher()]


def reconcile(
    bank: list[BankEntry],
    ledger: list[LedgerEntry],
    definition: "WorkflowDefinition | None" = None,
) -> ReconcileResult:
    # Import local de propósito: `definition.py` importa `default_resolvers`
    # deste módulo, e um import de topo nos dois sentidos seria circular.
    from orchestrator.workflow.definition import default_definition

    definicao = default_definition() if definition is None else definition
    work = WorkSet(bank=list(bank), ledger=list(ledger))
    todos: list[MatchResult] = []
    propostas: list[Proposal] = []
    custos: dict[str, Cost] = {}

    # A ordenação é POR STAGE, não global: um stage posterior não pode ter
    # seus resolvers embaralhados com os de um anterior. Com um stage só — o
    # caso de hoje — os dois dariam no mesmo; com dois, só este está certo.
    for stage in definicao.stages:
        for resolver in stage.ordered():
            saida = resolver.resolve(work)
            todos.extend(saida.matches)
            propostas.extend(saida.proposals)
            # Uma entrada por resolver que RODOU, mesmo que o custo seja
            # Cost.zero() — a ausência da chave é que sinaliza "não rodou".
            # Chave, não soma: cada resolver aparece com o PRÓPRIO custo, e um
            # selo na tela não teria como decompor um total do sistema.
            custos[resolver.name] = saida.cost
            # Só `matches` encolhe o pool. `saida.proposals` não aparece
            # nesta expressão, e é essa ausência que torna a invariante
            # estrutural em vez de uma regra que alguém precisa lembrar.
            work = work.without(saida.matches)

    return ReconcileResult(
        matches=todos,
        divergences=work.as_divergences(),
        proposals=propostas,
        cost_by_resolver=custos,
    )
