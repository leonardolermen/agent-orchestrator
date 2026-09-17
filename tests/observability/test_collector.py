"""O coletor de spans. Nada aqui importa domínio."""

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.event import EventBus
from orchestrator.kernel.policy import ExecutionPolicy
from orchestrator.kernel.resolution import (
    Confidence,
    Proposal,
    Resolution,
    TraceEvent,
    TraceKind,
)
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.trace import SpanKind, SpanStatus
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.observability.collector import SpanCollector
from orchestrator.runtime.engine import execute


class _R:
    def __init__(self, name="r", cost_class=CostClass.REGRA, resolve=(), propoe=()):
        self.name, self.cost_class = name, cost_class
        self._resolve, self._propoe = resolve, propoe

    def describe(self):
        return ResolverDescription(self.name, self.cost_class, "t")

    def resolve(self, work):
        presentes = work.ids()
        return ResolverOutput(
            resolutions=[
                Resolution(item_ids=frozenset({i}), produced_by=self.name, rule="t")
                for i in self._resolve
                if i in presentes
            ],
            proposals=list(self._propoe),
            cost=Cost(input_tokens=100, calls=1) if self._propoe else Cost.zero(),
        )


def _pool(*ids):
    return WorkSet(items=tuple(WorkItem(id=i, kind="k", payload=i) for i in ids))


def _wf(*resolvers, policy=None):
    return WorkflowDefinition(
        id="w",
        name="W",
        stages=(Stage("s", tuple(resolvers), policy=policy or ExecutionPolicy()),),
    )


def _rodar(definicao, work):
    bus = EventBus()
    coletor = SpanCollector().subscribe(bus)
    run = execute(definicao, work, bus=bus)
    return coletor.trace(run), run


def test_a_arvore_tem_uma_raiz_e_todo_pai_existe():
    trace, _ = _rodar(_wf(_R("L1", resolve=("a",))), _pool("a", "b"))

    raiz = trace.raiz()
    assert raiz is not None and raiz.kind is SpanKind.RUN

    ids = {s.id for s in trace.spans}
    orfaos = [s for s in trace.spans if s.parent_id and s.parent_id not in ids]
    assert orfaos == []


def test_span_de_POLITICA_existe_mesmo_quando_o_resolver_e_pulado():
    """Ele tem custo zero e duração ~0, e parece desperdício. Não é.

    É o registro de POR QUE o runtime não gastou dinheiro — a informação que
    diferencia "o agente não achou nada" de "a política não deixou o agente
    rodar". Sem ele, a decisão mais valiosa do sistema é a única que não deixa
    rastro.
    """
    trace, _ = _rodar(
        _wf(
            _R("L1"),
            _R("agente", CostClass.AGENTE),
            policy=ExecutionPolicy(max_cost_class=CostClass.REGRA),
        ),
        _pool("a"),
    )

    politicas = {s.name: s for s in trace.por_kind(SpanKind.POLICY)}
    assert politicas["agente"].status is SpanStatus.PULADO
    assert "teto" in politicas["agente"].attributes["motivo"]
    # E o resolver pulado NÃO produz span de resolver — ele não rodou.
    assert "agente" not in {s.name for s in trace.por_kind(SpanKind.RESOLVER)}


def test_a_lacuna_e_um_span_declarado_e_nao_uma_ausencia():
    """O canvas já a desenha, e o spec de composição §3.4 chama isso de "o
    ponto mais valioso da tela": declarar o que nenhum resolver cobriu."""
    trace, _ = _rodar(_wf(_R("L1", resolve=("a",))), _pool("a", "b"))

    lacuna = trace.por_kind(SpanKind.GAP)
    assert len(lacuna) == 1
    assert lacuna[0].attributes["itens"] == 1


def test_sem_lacuna_nao_ha_span_de_lacuna():
    trace, _ = _rodar(_wf(_R("L1", resolve=("a",))), _pool("a"))

    assert trace.por_kind(SpanKind.GAP) == ()


def test_custo_total_soma_FOLHAS_e_nao_a_arvore_inteira():
    """Somar todos os spans contaria cada token duas vezes — uma no span de
    LLM e outra no `resolver` que o contém. Agregar a agregação é o erro
    clássico desta estrutura."""
    proposta = Proposal(
        item_id="a",
        tipo="X",
        explicacao="",
        evidencia=[],
        confianca=Confidence.BAIXA,
        acao_sugerida="",
        cost=Cost(input_tokens=100, output_tokens=10, calls=1),
        trace=[
            TraceEvent(
                kind=TraceKind.LLM,
                detail={"turno": 1, "tokens_entrada": 100, "tokens_saida": 10},
            )
        ],
    )
    trace, _ = _rodar(
        _wf(_R("agente", CostClass.AGENTE, propoe=(proposta,))), _pool("a")
    )

    # O resolver custou 100 in; o item custou 100 in; o llm custou 100 in.
    # Somar os três daria o triplo. Só a FOLHA (llm) conta.
    llm = trace.por_kind(SpanKind.LLM)[0]
    assert trace.custo_total("claude-opus-5") == llm.cost.microcents("claude-opus-5")


def test_abstencao_NAO_e_erro():
    """Abstenção é o agente dizendo "não sei", e isso custou dinheiro.
    Colapsá-la em ERRO perderia a distinção entre "falhou" e "foi honesto"."""
    proposta = Proposal(
        item_id="a",
        tipo="NAO_SEI",
        explicacao="",
        evidencia=[],
        confianca=Confidence.BAIXA,
        acao_sugerida="",
        trace=[TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": "orçamento"})],
    )
    trace, _ = _rodar(
        _wf(_R("agente", CostClass.AGENTE, propoe=(proposta,))), _pool("a")
    )

    abstencoes = [s for s in trace.spans if s.status is SpanStatus.ABSTENCAO]
    assert len(abstencoes) == 1
    assert abstencoes[0].error is None


def test_erro_de_ferramenta_vira_span_de_erro_com_a_mensagem():
    proposta = Proposal(
        item_id="a",
        tipo="X",
        explicacao="",
        evidencia=[],
        confianca=Confidence.BAIXA,
        acao_sugerida="",
        trace=[
            TraceEvent(
                kind=TraceKind.TOOL,
                detail={
                    "nome": "buscar",
                    "resultado": {"erro": "limite inválido"},
                    "duracao_ms": 3,
                },
            )
        ],
    )
    trace, _ = _rodar(
        _wf(_R("agente", CostClass.AGENTE, propoe=(proposta,))), _pool("a")
    )

    tool = trace.por_kind(SpanKind.TOOL)[0]
    assert tool.status is SpanStatus.ERRO
    assert tool.error == "limite inválido"
    assert tool.duration_ms == 3


def test_o_resolver_carrega_latencia_que_Cost_nao_mede():
    """"O L3 levou 900ms" separa uma cascata CARA de uma cascata LENTA — duas
    coisas diferentes que até o M4 eram indistinguíveis, porque `Cost` só mede
    token."""
    trace, _ = _rodar(_wf(_R("L1", resolve=("a",))), _pool("a"))

    resolver = trace.por_kind(SpanKind.RESOLVER)[0]
    assert resolver.duration_ms >= 0
    assert resolver.attributes["cost_class"] == "REGRA"


def test_coletar_NAO_muda_o_resultado_da_execucao():
    """Observabilidade é ortogonal ao resultado. Se não fosse, o golden
    dependeria de quem está assinando."""
    definicao = _wf(_R("L1", resolve=("a",)))

    com, _ = _rodar(definicao, _pool("a", "b"))
    sem = execute(definicao, _pool("a", "b"), run_id="fixo")

    assert len(com.spans) > 0
    assert [r.item_ids for r in sem.resolutions] == [frozenset({"a"})]
    assert len(sem.unresolved.items) == 1


class _Transformador:
    """Resolve carregando o rastro em `Resolution.evidence`, como `Tarefa` faz.

    Não propõe NADA: é o formato de `domains/redacao` e de qualquer pipeline de
    pura transformação, em que `run.proposals` fica vazio.
    """

    cost_class = CostClass.AGENTE

    def __init__(self, name="tarefa", evidencia=None):
        self.name = name
        self._evidencia = {} if evidencia is None else evidencia

    def describe(self):
        return ResolverDescription(self.name, self.cost_class, "t")

    def resolve(self, work):
        return ResolverOutput(
            resolutions=[
                Resolution(
                    item_ids=frozenset({i.id}),
                    produced_by=self.name,
                    rule="transformou",
                    evidence=self._evidencia,
                )
                for i in work.items
            ],
            cost=Cost(input_tokens=100, calls=1),
        )


def test_resolucao_com_rastro_na_evidencia_vira_span_de_item_e_llm():
    """Um pipeline só de `Tarefa` não propõe nada — e enquanto o coletor só lia
    `run.proposals`, um run que chamou o modelo três vezes rendia ZERO span de
    item, llm ou tool. O rastro existia; ninguém o lia de volta."""
    rastro = (
        TraceEvent(
            kind=TraceKind.LLM,
            detail={"turno": 1, "tokens_entrada": 100, "tokens_saida": 7},
        ),
        TraceEvent(
            kind=TraceKind.TOOL, detail={"nome": "buscar", "resultado": {}, "duracao_ms": 2}
        ),
    )
    trace, run = _rodar(_wf(_Transformador(evidencia={"trace": rastro})), _pool("a"))

    assert run.proposals == ()
    itens = trace.por_kind(SpanKind.ITEM)
    assert [s.name for s in itens] == ["a"]
    assert itens[0].attributes["produced_by"] == "tarefa"
    # O pai é o resolver que resolveu, por `produced_by` — sem a aproximação
    # que `_propositor` precisa fazer, porque `Resolution` carrega proveniência.
    resolver = trace.por_kind(SpanKind.RESOLVER)[0]
    assert itens[0].parent_id == resolver.id
    assert len(trace.por_kind(SpanKind.LLM)) == 1
    assert trace.por_kind(SpanKind.TOOL)[0].name == "buscar"


def test_evidencia_malformada_e_pulada_sem_explodir():
    """`evidence` é `Mapping[str, Any]` preenchido por DOMÍNIO: chave ausente,
    tipo errado ou lista de lixo são todos possíveis, e nenhum pode quebrar
    `orchestrator trace`."""
    for evidencia in (
        {},
        {"trace": "não é uma tupla"},
        {"trace": 42},
        {"trace": ("nem isto", None, 7)},
        {"trace": ()},
        {"outra_coisa": "sem trace nenhum"},
    ):
        trace, _ = _rodar(_wf(_Transformador(evidencia=evidencia)), _pool("a"))

        assert trace.por_kind(SpanKind.ITEM) == ()
        # A árvore continua íntegra: a evidência ruim não derruba o resto.
        assert trace.raiz() is not None
