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
    # Ao lado de `matches_por_resolver`, e NUNCA no lugar dele: um conta
    # RESOLUÇÕES, o outro conta ITENS consumidos por elas. Os dois números
    # coincidem num domínio de um item por resolução e divergem por um fator 2
    # na conciliação, onde toda resolução casa ao menos um bancário com um
    # contábil. Manter os dois separados e nomeados é o que impede alguém de
    # refundi-los — dividir contagem de resolução pelo tamanho do pool já
    # produziu uma taxa pela metade na tela.
    itens_por_resolver: dict[str, int] = {}
    matches_por_classe: dict[CostClass, list[Resolution]] = {}

    rondas = 0
    estado_por_teto = False
    for _ in range(definicao.max_rondas):
        rondas += 1
        antes_resolvidos, antes_itens = len(todos), work.ids()
        emitir(EventKind.RONDA_INICIADA, ronda=rondas, itens=len(work.items))

        # A ordenação é POR STAGE, não global: um stage posterior não pode ter
        # seus resolvers embaralhados com os de um anterior. Com um stage só —
        # o caso de hoje — os dois dariam no mesmo; com dois, só este está
        # certo.
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
                # `produz` vazio significa "não produz nada", e um resolver que
                # produz mesmo assim é exatamente o caso que esta guarda pega.
                for novo in saida.produced:
                    if novo.kind not in stage.produz:
                        raise ValueError(
                            f"{resolver.name!r} produziu kind não declarado: "
                            f"{novo.kind!r} não está em produz={sorted(stage.produz)} "
                            f"do stage {stage.name!r}"
                        )
                todos.extend(saida.resolutions)
                propostas.extend(saida.proposals)
                # Uma entrada por resolver que RODOU, mesmo que o custo seja
                # Cost.zero() — a ausência da chave é que sinaliza "não rodou".
                # `.get(..., Cost.zero())` só cria a chave quando o resolver
                # roda, então essa invariante sobrevive.
                #
                # SOMA, não atribuição: com o laço de rondas, o MESMO resolver
                # pode rodar em mais de uma ronda (aresta de volta), e cada
                # rodada é uma contribuição a mais, não a substituição da
                # anterior. Uma atribuição aqui subcontaria o gasto real — e
                # `_somar(custos)` alimenta `pctx.spent`, o número que a
                # política compara contra o teto de orçamento. Subcontar gasto
                # é abrir exatamente o buraco que `max_rondas` existe para
                # fechar: um laço caro que a política não vê a tempo de parar.
                custos[resolver.name] = custos.get(resolver.name, Cost.zero()) + saida.cost
                # Mesma soma, mesmo motivo: `resolved_by_resolver` é uma
                # contagem por resolver ao longo do run inteiro, não só da
                # última ronda em que ele rodou.
                matches_por_resolver[resolver.name] = (
                    matches_por_resolver.get(resolver.name, 0) + len(saida.resolutions)
                )
                # Itens, na mesma soma acumulada e pelo mesmo motivo.
                #
                # **Isto é uma AFIRMAÇÃO do resolver, não uma medição do pool.**
                # `item_ids` é o que o resolver diz ter consumido; quem
                # realmente encolhe é `work.without(...)`, que ignora id que não
                # está no pool. Dois resolvers do mesmo stage citando o mesmo id
                # — ou um resolver citando id que não recebeu — fazem esta soma
                # passar do tamanho do pool, e nada aqui impede. É deliberado:
                # a LACUNA continua saindo de `unresolved`, contada, então ela
                # nunca mente; a soma por resolver é declarativa, e uma soma
                # que estoura vira sintoma visível em vez de lacuna negativa.
                itens_por_resolver[resolver.name] = itens_por_resolver.get(
                    resolver.name, 0
                ) + sum(len(r.item_ids) for r in saida.resolutions)
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

        # Ponto fixo: a ronda não resolveu nada E não mudou o pool. Rodar de
        # novo daria exatamente o mesmo resultado, porque o motor é puro e o
        # pool é a única entrada que muda entre rondas.
        if len(todos) == antes_resolvidos and work.ids() == antes_itens:
            break
    else:
        # `for/else`: o laço esgotou `max_rondas` sem um `break` — a última
        # ronda ainda estava fazendo coisa, logo não convergiu.
        #
        # `max_rondas == 1` NÃO conta como teto batido, e isso não é
        # conveniência: uma passada só não PROMETE convergência, ela promete
        # uma passada e a entrega. Declarar mais de uma ronda é o que cria a
        # expectativa de ponto fixo — e é só aí que não alcançá-lo é notícia.
        #
        # Sem esta condição, todo workflow de hoje (todos têm max_rondas=1 e
        # todos fazem trabalho) reportaria LIMITE_DE_RONDAS em vez de
        # CONCLUIDO, e os 844 testes cairiam juntos. A §5 do spec é explícita:
        # "1 = a semântica de hoje, EXATA".
        estado_por_teto = definicao.max_rondas > 1

    # Sobrou item E a cascata tem um degrau humano -> o run espera alguém.
    # Antes isso era "a lacuna", sem nome e sem como perguntar.
    tem_humano = any(
        r.cost_class >= CostClass.HUMANO for s in definicao.stages for r in s.cascade
    )
    if estado_por_teto:
        estado = RunState.LIMITE_DE_RONDAS
    elif work.items and tem_humano:
        estado = RunState.AGUARDANDO_HUMANO
    else:
        estado = RunState.CONCLUIDO
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
        resolved_items_by_resolver=itens_por_resolver,
        resolutions_by_class=matches_por_classe,
        policy_decisions=tuple(decisoes),
        rondas=rondas,
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
