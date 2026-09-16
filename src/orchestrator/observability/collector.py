"""De eventos para spans. O domínio nunca sabe que está sendo observado.

**Como os spans são produzidos:** pelo coletor, assinando o `EventBus`. Não por
decorator, não por monkey-patching, não por context manager espalhado pelo
código de domínio. Um resolver não importa nada daqui — ele emite eventos pelo
motor, e a observabilidade é um assinante.

É o que permite testar todo resolver sem instrumentação e desligar a
observabilidade inteira sem tocar em lógica. Há teste provando que ligar e
desligar o barramento produz o mesmo resultado (`test_run.py`).

**A limitação, declarada.** Os spans de `run`, `stage`, `policy` e `resolver`
vêm do STREAM de eventos. Os de `item`, `llm` e `tool` são DERIVADOS de
`Proposal.trace` depois que o run termina — porque quem sabe deles é o agente, e
o agente ainda não recebe o barramento. Fechar isso exige `Resolver.resolve(work,
ctx)` com um contexto de execução, que é mudança de assinatura em todo resolver
e está agendada para o M6 (confiabilidade), onde ela também paga por timeout e
cancelamento.

Consequência prática: a árvore de `orchestrator trace <run-id>` é completa, mas
o detalhe de LLM e ferramenta só existe DEPOIS do run, não durante. Para
observabilidade ao vivo — que ninguém pediu ainda — falta aquele contexto.
"""

import itertools
from datetime import datetime

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.event import Event, EventBus, EventKind
from orchestrator.kernel.resolution import Proposal, TraceKind
from orchestrator.kernel.run import Run
from orchestrator.kernel.trace import Span, SpanKind, SpanStatus, Trace


class SpanCollector:
    """Assina o barramento e monta a árvore.

    Guarda o estado mínimo para saber quem é pai de quem: o span de run, o
    stage aberto e o resolver aberto. Um evento que chegue fora de ordem (não
    acontece hoje — o motor é síncrono e determinístico) produziria um span
    órfão, e `Trace.raiz()` o denunciaria em vez de escondê-lo.
    """

    def __init__(self) -> None:
        self._spans: list[Span] = []
        self._seq = itertools.count()
        self._run_id: str | None = None
        self._run_span: str | None = None
        self._stage_span: str | None = None
        self._abertos: dict[str, tuple[str, datetime]] = {}
        self._run_inicio: datetime | None = None

    # -- assinatura -------------------------------------------------------

    def subscribe(self, bus: EventBus) -> "SpanCollector":
        bus.subscribe(None, self.on_event)
        return self

    def _novo_id(self, prefixo: str) -> str:
        return f"{prefixo}-{next(self._seq):04d}"

    def on_event(self, e: Event) -> None:
        p = e.payload
        if e.kind is EventKind.RUN_INICIADO:
            self._run_id = e.run_id
            self._run_inicio = e.at
            self._run_span = self._novo_id("run")
            self._spans.append(
                Span(
                    id=self._run_span,
                    parent_id=None,
                    kind=SpanKind.RUN,
                    name=f"{p.get('workflow')}@{p.get('version', '')[:8]}",
                    started_at=e.at,
                    attributes={"itens": p.get("itens", 0)},
                )
            )
        elif e.kind is EventKind.STAGE_INICIADO:
            self._stage_span = self._novo_id("stage")
            self._spans.append(
                Span(
                    id=self._stage_span,
                    parent_id=self._run_span,
                    kind=SpanKind.STAGE,
                    name=p.get("stage", ""),
                    started_at=e.at,
                )
            )
        elif e.kind is EventKind.POLITICA_DECIDIU:
            # O span de política tem custo zero e duração ~0, e parece
            # desperdício. Não é: ele é o registro de POR QUE o runtime não
            # gastou dinheiro — a informação que diferencia "o agente não achou
            # nada" de "a política não deixou o agente rodar". Sem ele, a
            # decisão mais valiosa do sistema é a única que não deixa rastro.
            self._spans.append(
                Span(
                    id=self._novo_id("pol"),
                    parent_id=self._stage_span,
                    kind=SpanKind.POLICY,
                    name=p.get("resolver", ""),
                    status=(
                        SpanStatus.PULADO
                        if p.get("rota") != "executar"
                        else SpanStatus.OK
                    ),
                    started_at=e.at,
                    attributes={
                        "rota": p.get("rota"),
                        "motivo": p.get("motivo"),
                        **({"item": p["item"]} if p.get("item") else {}),
                    },
                )
            )
        elif e.kind is EventKind.RESOLVER_INICIADO:
            sid = self._novo_id("res")
            self._abertos[p["resolver"]] = (sid, e.at)
        elif e.kind is EventKind.RESOLVER_CONCLUIDO:
            aberto = self._abertos.pop(p["resolver"], None)
            sid, inicio = aberto or (self._novo_id("res"), e.at)
            self._spans.append(
                Span(
                    id=sid,
                    parent_id=self._stage_span,
                    kind=SpanKind.RESOLVER,
                    name=p["resolver"],
                    started_at=inicio,
                    duration_ms=p.get("duracao_ms", 0),
                    cost=p.get("cost") or Cost.zero(),
                    attributes={
                        "cost_class": p.get("cost_class"),
                        "resolveu": p.get("resolveu", 0),
                        "propos": p.get("propos", 0),
                    },
                )
            )
        elif e.kind is EventKind.RUN_CONCLUIDO and self._run_span:
            self._fechar_run(e)

    def _fechar_run(self, e: Event) -> None:
        raiz = next(s for s in self._spans if s.id == self._run_span)
        inicio = self._run_inicio or e.at
        atualizado = Span(
            id=raiz.id,
            parent_id=None,
            kind=raiz.kind,
            name=raiz.name,
            status=raiz.status,
            started_at=inicio,
            duration_ms=int((e.at - inicio).total_seconds() * 1000),
            cost=raiz.cost,
            attributes={**raiz.attributes, **e.payload},
        )
        self._spans = [atualizado if s.id == raiz.id else s for s in self._spans]
        # A LACUNA como span. O canvas já a desenha, e o spec de composição
        # §3.4 chama isso de "o ponto mais valioso da tela": declarar o que
        # nenhum resolver cobriu, em vez de esconder.
        pendentes = e.payload.get("pendentes", 0)
        if pendentes:
            self._spans.append(
                Span(
                    id=self._novo_id("gap"),
                    parent_id=self._run_span,
                    kind=SpanKind.GAP,
                    name="lacuna",
                    status=SpanStatus.PULADO,
                    started_at=e.at,
                    attributes={"itens": pendentes},
                )
            )

    # -- resultado --------------------------------------------------------

    def trace(self, run: Run | None = None) -> Trace:
        """A árvore. Com o `Run`, inclui o detalhe por item.

        O detalhe vem de `Proposal.trace`, e não do stream, pela razão do
        docstring do módulo. `Trace` não sabe a diferença — quem lê um span de
        `llm` não precisa saber se ele foi emitido ou derivado.
        """
        spans = list(self._spans)
        if run is not None:
            spans.extend(self._de_propostas(run))
        return Trace(run_id=self._run_id or (run.id if run else ""), spans=tuple(spans))

    def _de_propostas(self, run: Run) -> list[Span]:
        achados: list[Span] = []
        for proposta in run.proposals:
            pai = self._propositor()
            item_id = self._novo_id("item")
            achados.append(
                Span(
                    id=item_id,
                    parent_id=pai,
                    kind=SpanKind.ITEM,
                    name=proposta.item_id,
                    status=(
                        SpanStatus.ERRO
                        if any(t.kind is TraceKind.ERRO for t in proposta.trace)
                        else SpanStatus.OK
                    ),
                    cost=proposta.cost,
                    attributes={
                        "tipo": proposta.tipo,
                        "confianca": proposta.confianca.value,
                        "evidencias": len(proposta.evidencia),
                    },
                )
            )
            achados.extend(self._de_trace(proposta, item_id))
        return achados

    def _propositor(self) -> str | None:
        """O span do resolver que propôs.

        `Proposal` não carrega o nome de quem a produziu — e não deveria:
        proposta é do domínio, resolver é da cascata.

        **Aproximação declarada:** hoje há no máximo um resolver que propõe por
        stage (só classe AGENTE propõe, e as cascatas têm um agente). Com dois,
        toda proposta seria atribuída ao último, e a árvore mentiria. Fechar
        isso exige `ResolverOutput` carregar a atribuição — e o dia em que um
        stage tiver dois agentes é o dia em que esta função precisa mudar, não
        antes.
        """
        propositores = [
            s
            for s in self._spans
            if s.kind is SpanKind.RESOLVER and s.attributes.get("propos", 0) > 0
        ]
        return propositores[-1].id if propositores else self._stage_span

    def _de_trace(self, proposta: Proposal, pai: str) -> list[Span]:
        achados = []
        for t in proposta.trace:
            if t.kind is TraceKind.LLM:
                achados.append(
                    Span(
                        id=self._novo_id("llm"),
                        parent_id=pai,
                        kind=SpanKind.LLM,
                        name=f"turno {t.detail.get('turno', '?')}",
                        cost=Cost(
                            input_tokens=t.detail.get("tokens_entrada", 0),
                            output_tokens=t.detail.get("tokens_saida", 0),
                            calls=1,
                        ),
                        attributes={"stop_reason": t.detail.get("stop_reason")},
                    )
                )
            elif t.kind is TraceKind.TOOL:
                resultado = t.detail.get("resultado")
                erro = (
                    resultado.get("erro") if isinstance(resultado, dict) else None
                )
                achados.append(
                    Span(
                        id=self._novo_id("tool"),
                        parent_id=pai,
                        kind=SpanKind.TOOL,
                        name=t.detail.get("nome", "?"),
                        status=SpanStatus.ERRO if erro else SpanStatus.OK,
                        duration_ms=t.detail.get("duracao_ms", 0),
                        error=erro,
                        attributes={"argumentos": t.detail.get("argumentos")},
                    )
                )
            elif t.kind is TraceKind.OUTCOME and t.detail.get("motivo"):
                # Abstenção NÃO é erro: é o agente dizendo "não sei", e isso
                # custou dinheiro. Colapsá-la em ERRO perderia a distinção
                # entre "falhou" e "foi honesto".
                achados.append(
                    Span(
                        id=self._novo_id("out"),
                        parent_id=pai,
                        kind=SpanKind.ITEM,
                        name="abstenção",
                        status=SpanStatus.ABSTENCAO,
                        attributes={"motivo": t.detail["motivo"]},
                    )
                )
        return achados
