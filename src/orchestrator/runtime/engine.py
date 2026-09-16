"""Orquestra a cascata de resolução e apura o que sobrou.

Cada resolver recebe apenas o que os anteriores não resolveram. O que nenhum
resolveu fica no `WorkSet` final — e é esse resto, e só ele, que o domínio
transforma no que quer que ele chame de pendência. Ver spec 4.3.

**O motor não conhece domínio nenhum.** Ele recebe uma `WorkflowDefinition` e um
`WorkSet`, e devolve `ExecutionResult`. Antes devolvia `ReconcileResult`, com
`divergences: list[Divergence]` — e por isso o runtime importava `models`.
Quem transforma o resto em `Divergence` é `conciliacao.reconcile()`.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import WorkflowDefinition
from orchestrator.kernel.resolution import Proposal, Resolution
from orchestrator.kernel.work import WorkSet


@dataclass(frozen=True)
class ExecutionResult:
    """O que uma execução produziu. Genérico: nenhum campo de conciliação.

    Vira `Run` no PR #7, com id, estado e timestamps. Os nomes dos campos já
    são os de lá, para que aquele PR acrescente em vez de renomear.
    """

    resolutions: list[Resolution]
    # O que NENHUM resolver resolveu, ainda como pool. Antes era
    # `divergences: list[Divergence]` — o motor derivava a forma de pendência
    # do domínio. Devolver o `WorkSet` deixa essa derivação com quem sabe o que
    # ela significa, e é o que tira `runtime -> domains` da lista de violações.
    unresolved: WorkSet
    proposals: list[Proposal] = field(default_factory=list)
    # Custo por resolver, não do sistema. Um resolver que rodou e não custou
    # nada aparece com Cost.zero(); um que não rodou não aparece. A diferença
    # importa na tela: "de graça" e "não rodou" são coisas diferentes.
    cost_by_resolver: dict[str, Cost] = field(default_factory=dict)
    # Contagem por IDENTIDADE do resolver (`Resolver.name`), não por
    # proveniência (`Resolution.produced_by`) — ver P3.2 em DECISOES.md. Os
    # dois coincidem hoje porque cada resolver só produz resoluções com o
    # próprio nome, mas são conceitos diferentes por desenho.
    resolved_by_resolver: dict[str, int] = field(default_factory=dict)
    # As resoluções agrupadas pela CLASSE do resolver que as produziu, capturada
    # no laço. Sem isto, a única forma de separar trabalho de regra de trabalho
    # humano seria olhar `Resolution.produced_by` — proveniência, não classe —
    # que é o mesmo join frágil que P3.2 manda evitar.
    resolutions_by_class: dict[CostClass, list[Resolution]] = field(default_factory=dict)


def execute(definition: WorkflowDefinition, work: WorkSet) -> ExecutionResult:
    """Roda uma definição sobre um pool. Puro: não lê disco, não chama rede.

    `definition` é OBRIGATÓRIA, e é essa obrigatoriedade que quebra a
    circularidade. Antes, `reconcile` caía para `default_definition()` — a
    cascata de conciliação — e por isso o motor precisava importar o módulo que
    importava o motor. Os dois imports locais que escondiam isso do
    interpretador sumiram com ela.

    Quem tem um default é o DOMÍNIO: `conciliacao.reconcile()` continua
    aceitando `definition=None` e continua sendo a porta que a CLI, a API e o
    grill usam. O motor não conhece cascata nenhuma.
    """
    definicao = definition
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

    return ExecutionResult(
        resolutions=todos,
        unresolved=work,
        proposals=propostas,
        cost_by_resolver=custos,
        resolved_by_resolver=matches_por_resolver,
        resolutions_by_class=matches_por_classe,
    )
