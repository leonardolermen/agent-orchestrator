"""Orquestra a cascata de resolução e apura o que sobrou.

Cada resolver recebe apenas o que os anteriores não resolveram. O que nenhum
resolveu vira Divergence — e é isso, e só isso, que o agente de investigação
recebe. Ver spec 4.3.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orchestrator.agent.proposal import Proposal
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.matching.exact import ExactMatcher
from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.matching.tolerance import ToleranceMatcher
from orchestrator.models import BankEntry, Divergence, LedgerEntry, divergencias, pool
from orchestrator.workflow.resolver import Resolver

if TYPE_CHECKING:
    # Só para o type checker: em tempo de execução este import viraria
    # circular (`definition.py` importa `default_resolvers` deste módulo). O
    # import de verdade, usado dentro de `reconcile`, é local de propósito.
    from orchestrator.workflow.definition import WorkflowDefinition


@dataclass(frozen=True)
class ReconcileResult:
    matches: list[Resolution]
    divergences: list[Divergence]
    proposals: list[Proposal] = field(default_factory=list)
    # Custo por resolver, não do sistema. Um resolver que rodou e não custou
    # nada aparece com Cost.zero(); um que não rodou não aparece. A diferença
    # importa na tela: "de graça" e "não rodou" são coisas diferentes.
    cost_by_resolver: dict[str, Cost] = field(default_factory=dict)
    # Contagem por IDENTIDADE do resolver (`Resolver.name`), não por
    # proveniência (`Resolution.produced_by`) — ver P3.2 em DECISOES.md. Os dois
    # coincidem hoje porque cada resolver só produz matches com o próprio
    # nome como `layer`, mas são conceitos diferentes por desenho: `layer` é
    # "quem produziu este vínculo", `name` é "quem é o resolver na cascata".
    # `Metrics.matches_by_layer` continua a fonte de proveniência; este campo
    # é o que a tela precisa para nunca reportar 0% de um resolver que rodou
    # e apenas estampou seus matches com uma proveniência diferente do nome.
    matches_by_resolver: dict[str, int] = field(default_factory=dict)
    # Os matches agrupados pela CLASSE do resolver que os produziu, capturada
    # no laço. Sem isto, a única forma de separar match de regra de match
    # humano seria olhar `Resolution.produced_by` — proveniência, não classe — que
    # é o mesmo join frágil que P3.2 manda evitar.
    matches_by_class: dict[CostClass, list[Resolution]] = field(default_factory=dict)


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
    work = pool(bank, ledger)
    todos: list[Resolution] = []
    propostas: list[Proposal] = []
    custos: dict[str, Cost] = {}
    matches_por_resolver: dict[str, int] = {}
    matches_por_classe: dict[CostClass, list[Resolution]] = {}

    # A ordenação é POR STAGE, não global: um stage posterior não pode ter
    # seus resolvers embaralhados com os de um anterior. Com um stage só — o
    # caso de hoje — os dois dariam no mesmo; com dois, só este está certo.
    for stage in definicao.stages:
        for resolver in stage.ordered():
            saida = resolver.resolve(work)
            todos.extend(saida.resolutions)
            propostas.extend(saida.proposals)
            # Uma entrada por resolver que RODOU, mesmo que o custo seja
            # Cost.zero() — a ausência da chave é que sinaliza "não rodou".
            # Chave, não soma: cada resolver aparece com o PRÓPRIO custo, e um
            # selo na tela não teria como decompor um total do sistema.
            custos[resolver.name] = saida.cost
            # Chave por identidade do resolver, não por `layer` do match — a
            # mesma distinção do comentário em `matches_by_resolver` acima.
            matches_por_resolver[resolver.name] = len(saida.resolutions)
            matches_por_classe.setdefault(resolver.cost_class, []).extend(saida.resolutions)
            # Só `resolutions` encolhe o pool. `saida.proposals` não aparece
            # nesta expressão, e é essa ausência que torna a invariante
            # estrutural em vez de uma regra que alguém precisa lembrar.
            work = work.without(saida.resolutions)

    return ReconcileResult(
        matches=todos,
        divergences=divergencias(work),
        proposals=propostas,
        cost_by_resolver=custos,
        matches_by_resolver=matches_por_resolver,
        matches_by_class=matches_por_classe,
    )
