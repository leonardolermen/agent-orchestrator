"""Orquestra a cascata de resolução e apura o que sobrou.

Cada resolver recebe apenas o que os anteriores não resolveram. O que nenhum
resolveu fica no `WorkSet` final — e é esse resto, e só ele, que o domínio
transforma no que quer que ele chame de pendência. Ver spec 4.3.

**O motor não conhece domínio nenhum.** Ele recebe uma `WorkflowDefinition` e um
`WorkSet`, e devolve um `Run`. Já devolveu `ReconcileResult`, com
`divergences: list[Divergence]` — e por isso o runtime importava `models`.
Quem transforma o resto em `Divergence` é `conciliacao.reconcile()`.
"""

from datetime import UTC, datetime

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import WorkflowDefinition
from orchestrator.kernel.event import Event, EventBus, EventKind, NullBus
from orchestrator.kernel.resolution import Proposal, Resolution
from orchestrator.kernel.run import Run, RunState, new_run_id
from orchestrator.kernel.work import WorkSet


def execute(
    definition: WorkflowDefinition,
    work: WorkSet,
    *,
    bus: EventBus | None = None,
    input_ref: str = "",
    run_id: str | None = None,
) -> Run:
    """Roda uma definição sobre um pool. Puro: não lê disco, não chama rede.

    `definition` é OBRIGATÓRIA, e é essa obrigatoriedade que quebra a
    circularidade. Antes, `reconcile` caía para `default_definition()` — a
    cascata de conciliação — e por isso o motor precisava importar o módulo que
    importava o motor. Os dois imports locais que escondiam isso do
    interpretador sumiram com ela.

    Quem tem um default é o DOMÍNIO: `conciliacao.reconcile()` continua
    aceitando `definition=None` e continua sendo a porta que a CLI, a API e o
    grill usam. O motor não conhece cascata nenhuma.

    Desde o PR #7 devolve um `Run`, com identidade, estado e duração. Continua
    PURO: não lê disco, não chama rede, e não persiste. Quem persiste é o
    chamador, com um `RunStore` — é isso que mantém o golden e o teste de
    "nenhum endpoint gasta dinheiro" valendo.

    `bus` é opcional e o default não emite nada (`NullBus`), de modo que
    desligar observabilidade é trocar um objeto e não mudar o laço. Eventos
    OBSERVAM: nada aqui reage a um deles para decidir o que roda em seguida.
    """
    barramento = bus or NullBus()
    rid = run_id or new_run_id()
    inicio = datetime.now(UTC)

    def emitir(kind: EventKind, **payload) -> None:
        barramento.emit(
            Event(kind=kind, run_id=rid, at=datetime.now(UTC), payload=payload)
        )

    definicao = definition
    emitir(
        EventKind.RUN_INICIADO,
        workflow=definicao.id,
        version=definicao.version,
        itens=len(work.items),
    )
    todos: list[Resolution] = []
    propostas: list[Proposal] = []
    custos: dict[str, Cost] = {}
    matches_por_resolver: dict[str, int] = {}
    matches_por_classe: dict[CostClass, list[Resolution]] = {}

    # A ordenação é POR STAGE, não global: um stage posterior não pode ter
    # seus resolvers embaralhados com os de um anterior. Com um stage só — o
    # caso de hoje — os dois dariam no mesmo; com dois, só este está certo.
    for stage in definicao.stages:
        emitir(EventKind.STAGE_INICIADO, stage=stage.name)
        for resolver in stage.ordered():
            emitir(
                EventKind.RESOLVER_INICIADO,
                resolver=resolver.name,
                cost_class=resolver.cost_class.name,
                pendentes=len(work.items),
            )
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
            for r in saida.resolutions:
                emitir(
                    EventKind.ITEM_RESOLVIDO,
                    resolver=resolver.name,
                    item_ids=sorted(r.item_ids),
                )
            for prop in saida.proposals:
                emitir(
                    EventKind.ITEM_PROPOSTO,
                    resolver=resolver.name,
                    item_id=prop.item_id,
                    tipo=prop.tipo,
                    confianca=prop.confianca.value,
                )
            emitir(
                EventKind.RESOLVER_CONCLUIDO,
                resolver=resolver.name,
                resolveu=len(saida.resolutions),
                propos=len(saida.proposals),
            )

    # Sobrou item E a cascata tem um degrau humano -> o run espera alguém.
    # Antes isso era "a lacuna", sem nome e sem como perguntar.
    tem_humano = any(
        r.cost_class >= CostClass.HUMANO for s in definicao.stages for r in s.cascade
    )
    estado = (
        RunState.AGUARDANDO_HUMANO
        if work.items and tem_humano
        else RunState.CONCLUIDO
    )
    fim = datetime.now(UTC)
    emitir(
        EventKind.RUN_CONCLUIDO,
        estado=estado.value,
        resolvidos=len(todos),
        pendentes=len(work.items),
    )
    return Run(
        id=rid,
        workflow_id=definicao.id,
        workflow_version=definicao.version,
        state=estado,
        started_at=inicio,
        finished_at=fim,
        input_ref=input_ref,
        resolutions=tuple(todos),
        proposals=tuple(propostas),
        unresolved=work,
        cost_by_resolver=custos,
        resolved_by_resolver=matches_por_resolver,
        resolutions_by_class=matches_por_classe,
    )
