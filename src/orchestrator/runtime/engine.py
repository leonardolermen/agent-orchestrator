"""Orquestra a cascata de resolução e apura o que sobrou.

Cada resolver recebe apenas o que os anteriores não resolveram. O que nenhum
resolveu fica no `WorkSet` final — e é esse resto, e só ele, que o domínio
transforma no que quer que ele chame de pendência. Ver spec 4.3.

**O motor não conhece domínio nenhum.** Ele recebe uma `WorkflowDefinition` e um
`WorkSet`, e devolve um `Run`. Já devolveu `ReconcileResult`, com
`divergences: list[Divergence]` — e por isso o runtime importava `models`.
Quem transforma o resto em `Divergence` é `conciliacao.reconcile()`.
"""

import time
from datetime import UTC, datetime

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import WorkflowDefinition
from orchestrator.kernel.event import Event, EventBus, EventKind, NullBus
from orchestrator.kernel.policy import PolicyContext, PolicyDecision, Route
from orchestrator.kernel.resolution import Proposal, Resolution
from orchestrator.kernel.run import Run, RunState, new_run_id
from orchestrator.kernel.work import WorkSet
from orchestrator.runtime import policy_engine


def execute(
    definition: WorkflowDefinition,
    work: WorkSet,
    *,
    bus: EventBus | None = None,
    input_ref: str = "",
    run_id: str | None = None,
    policy: PolicyContext | None = None,
    model: str = "claude-opus-5",
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
    decisoes: list[PolicyDecision] = []
    pctx = policy or PolicyContext(model=model)
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
        # O que ESTE degrau enxerga. `consome` vazio = o pool inteiro.
        #
        # Guardamos o resto à parte e o recompomos no fim do stage: filtrar
        # sem recompor faria o pool encolher por um caminho que não é
        # `without()`, e a invariante "só resolução consome" cairia sem
        # ninguém notar.
        if stage.consome:
            visivel = WorkSet(
                items=tuple(i for i in work.items if i.kind in stage.consome)
            )
            reservados = tuple(i for i in work.items if i.kind not in stage.consome)
        else:
            visivel, reservados = work, ()
        if stage.consome and not visivel.items:
            # Ramo sem trabalho: o degrau não roda, e isso é a condicional.
            #
            # O gate é em `stage.consome`, não em `visivel.items` sozinho:
            # sem `consome` declarado (default, pool inteiro) um pool vazio já
            # rodava a cascata antes desta fatia — é o cenário que
            # `test_ordenacao_e_por_stage_nao_global` e vizinhos, em
            # `tests/matching/test_engine.py`, fixam ao chamar `reconcile([],
            # [], ...)` só para observar ORDEM, sem depender de item nenhum.
            # Sem este gate, "consome vazio = pool inteiro" deixaria de
            # reproduzir a semântica de hoje assim que o pool esvaziasse.
            emitir(EventKind.STAGE_CONCLUIDO, stage=stage.name, rodou=False)
            continue
        work = visivel
        for resolver in stage.ordered():
            # A POLÍTICA decide se este resolver roda. `Stage.ordered()`
            # continua sendo a ORDEM — as duas coisas são ortogonais, e é isso
            # que impede a política de chamar inteligência antes da regra de
            # graça (invariante nº 2 do §1.5).
            pctx.spent = _somar(custos)
            decisao = policy_engine.decide(resolver, stage.policy, pctx)
            decisoes.append(decisao)
            emitir(
                EventKind.POLITICA_DECIDIU,
                resolver=resolver.name,
                rota=decisao.route.value,
                motivo=decisao.reason,
            )
            if decisao.route is Route.PARAR:
                break
            if decisao.route is Route.PULAR:
                continue

            emitir(
                EventKind.RESOLVER_INICIADO,
                resolver=resolver.name,
                cost_class=resolver.cost_class.name,
                pendentes=len(work.items),
            )
            # Regras 6 e 7, por item: o pool que o resolver recebe pode ser
            # menor que o pool. Um item excluído sai com motivo registrado —
            # nunca em silêncio.
            elegiveis, por_item = policy_engine.filtrar(
                resolver, work, stage.policy, pctx
            )
            decisoes.extend(por_item)
            for d in por_item:
                emitir(
                    EventKind.POLITICA_DECIDIU,
                    resolver=resolver.name,
                    item=d.item_id,
                    rota=d.route.value,
                    motivo=d.reason,
                )
            comeco = time.perf_counter()
            saida = resolver.resolve(elegiveis)
            duracao_ms = int((time.perf_counter() - comeco) * 1000)
            # `produz` vazio = sem restrição declarada, o espelho exato do que
            # `consome` vazio já significa para o lado do consumo. A guarda só
            # entra quando o stage DECLAROU um `produz`: é o que mantém as 9
            # definições existentes — que nunca declararam nada — reproduzindo
            # a semântica de hoje, e reserva o erro para quem prometeu um
            # conjunto e entregou outro.
            if stage.produz:
                for novo in saida.produced:
                    if novo.kind not in stage.produz:
                        raise ValueError(
                            f"{resolver.name!r} produziu kind não declarado: "
                            f"{novo.kind!r} não está em produz="
                            f"{sorted(stage.produz)} do stage {stage.name!r}"
                        )
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
            # Só `resolutions` encolhe o pool e só `produced` o aumenta.
            # `saida.proposals` não aparece em nenhuma das duas expressões, e é
            # essa ausência que torna a invariante estrutural em vez de uma
            # regra que alguém precisa lembrar.
            work = work.without(saida.resolutions).com(saida.produced)
            for r in saida.resolutions:
                emitir(
                    EventKind.ITEM_RESOLVIDO,
                    resolver=resolver.name,
                    item_ids=sorted(r.item_ids),
                )
            for novo in saida.produced:
                emitir(
                    EventKind.ITEM_PRODUZIDO,
                    resolver=resolver.name,
                    item=novo.id,
                    # `item_kind`, não `kind`: `emitir()` já usa `kind` para o
                    # tipo do evento, e um payload `kind=` colidiria com esse
                    # parâmetro posicional.
                    item_kind=novo.kind,
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
                produziu=len(saida.produced),
                # Latência por resolver. `Cost` só mede token, e "o L3 levou
                # 900ms" é a informação que separa uma cascata cara de uma
                # cascata LENTA — duas coisas diferentes que até aqui eram
                # indistinguíveis.
                duracao_ms=duracao_ms,
                cost=saida.cost,
                cost_class=resolver.cost_class.name,
            )

        work = WorkSet(items=work.items + reservados)
        emitir(EventKind.STAGE_CONCLUIDO, stage=stage.name, rodou=True)

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
        policy_decisions=tuple(decisoes),
    )


def _somar(custos: dict[str, Cost]) -> Cost:
    """O gasto acumulado da execução, para a regra 2 da política.

    Somado a cada resolver e não mantido incremental de propósito: o dicionário
    é a fonte, e um acumulador paralelo seria mais um join frágil.
    """
    total = Cost.zero()
    for c in custos.values():
        total = total + c
    return total
