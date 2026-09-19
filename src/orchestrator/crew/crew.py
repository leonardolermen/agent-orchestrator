"""Vários agentes num item. Um `Resolver` como qualquer outro.

**A regra de contenção (§10.1).** `Crew` é um resolver de classe `CREW`, e nada
mais:

    CERTO                          ERRADO
    Workflow                       Crew
       └── Stage                      └── tudo
            └── Crew (um Resolver)
                 └── Agents

Não é preferência estética. Um Crew que fosse o topo precisaria da própria noção
de custo, política, trace e human-in-the-loop — quatro duplicações do que o
runtime já faz. Como resolver, ele herda tudo de graça: entra na cascata, é
ordenado por classe de custo (`CostClass.CREW` fica entre `AGENTE` e `HUMANO`,
onde sempre esteve), tem orçamento, emite trace, e o revisor humano continua
depois dele.

**Um Crew é mais opinião, não mais autoridade.** Ele devolve `proposals` e nunca
`resolutions`. Se um agente sozinho não pode resolver, três também não podem — e
deixar um Crew resolver seria a porta pela qual a invariante mais cara do projeto
sairia sem ninguém notar.

**Por que ele só chega agora.** O §10.5 é explícito: construir Crew antes do M6
seria construir uma capacidade cara sem instrumento para saber se ela melhora
alguma coisa. Com o M6 pronto, "tripulação vale o custo?" é um `BenchmarkArm`,
não uma opinião — e a resposta pode ser não.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from orchestrator.agent.agent import Agent, AgentTask
from orchestrator.crew.context import SharedContext
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import (
    Confidence,
    Proposal,
    TraceEvent,
    TraceKind,
)
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet


class Process(StrEnum):
    SEQUENTIAL = "sequential"
    HIERARCHICAL = "hierarchical"


class Conflito(StrEnum):
    """O que fazer quando dois agentes discordam sobre o mesmo item."""

    # Desacordo é INFORMAÇÃO. Vira proposta de baixa confiança com as duas
    # hipóteses na evidência, e o humano decide. Barato, honesto, e alimenta o
    # conjunto de avaliação com um caso genuinamente difícil — que é o tipo de
    # caso que um conjunto sintético não produz.
    ABSTER = "abster"
    # Um sintetizador lê o quadro branco e escreve a proposta final. Custa um
    # turno a mais.
    SINTETIZAR = "sintetizar"
    # Só com 3+ agentes e o mesmo esquema de saída. Barato, mas APAGA a
    # informação do desacordo — por isso não é o default.
    MAIORIA = "maioria"


# Voto ponderado por confiança declarada está explicitamente FORA. Confiança de
# LLM não é calibrada, e ponderar por ela daria autoridade a um número que o M6
# ainda vai medir se significa alguma coisa. Quando medir, a decisão se revisita
# com dado; até lá, não.
_CHAVE = "conclusao"


@dataclass
class Crew:
    """Uma tripulação. Resolver de classe `CREW`."""

    name: str
    agents: tuple[Agent, ...]
    # Quais valores de `Proposal.tipo` significam "não sei" NESTE domínio.
    # Obrigatório, e pela mesma razão que `medir` o exige: sem isso o Crew
    # compararia uma abstenção com uma resposta e chamaria de desacordo.
    abstem_com: frozenset[str]
    process: Process = Process.SEQUENTIAL
    conflito: Conflito = Conflito.ABSTER
    manager: Agent | None = None
    synthesizer: Agent | None = None
    max_rounds: int = 1
    # Teto do Crew INTEIRO, não por agente. Um teto por agente multiplicaria o
    # orçamento pelo tamanho da tripulação sem ninguém decidir isso.
    budget_microcents: int = 20_000_000
    cost_class: CostClass = field(default=CostClass.CREW, init=False)

    def __post_init__(self) -> None:
        if not self.agents:
            raise ValueError(
                f"tripulação {self.name!r} sem agente: um Crew vazio devolveria "
                f"zero propostas e pareceria um resolver que não achou nada"
            )
        if self.process is Process.HIERARCHICAL and self.manager is None:
            raise ValueError(
                f"{self.name!r} é HIERARCHICAL e não tem `manager`. sem gerente "
                f"não há quem roteie, e o modo degenera em sequencial caro"
            )
        if self.conflito is Conflito.SINTETIZAR and self.synthesizer is None:
            raise ValueError(
                f"{self.name!r} resolve conflito por síntese e não tem "
                f"`synthesizer`. o conflito ficaria sem resolução e o item "
                f"sairia sem proposta"
            )
        if self.conflito is Conflito.MAIORIA and len(self.agents) < 3:
            raise ValueError(
                f"{self.name!r} resolve conflito por maioria com "
                f"{len(self.agents)} agente(s). com dois não há maioria — há "
                f"empate, e empate por maioria é abstenção com passos extras"
            )
        if self.max_rounds < 1:
            raise ValueError(f"max_rounds precisa ser >= 1: {self.max_rounds}")
        if self.process is Process.SEQUENTIAL and len(self.agents) < 2:
            raise ValueError(
                f"{self.name!r} é sequencial com um agente só. isso é um "
                f"`Agent`, e pagar `CostClass.CREW` por ele faria a cascata "
                f"colocá-lo depois de agentes mais baratos sem motivo"
            )

    # -- contrato de Resolver ---------------------------------------------

    def describe(self) -> ResolverDescription:
        quem = ", ".join(a.name for a in self.agents)
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=f"tripulação {self.process.value} [{quem}]",
            # A UNIÃO do que os agentes consomem, e não vazio.
            #
            # Vazio significa "vejo o pool inteiro", e enquanto ninguém compunha
            # um Crew na tela isso não custava nada — o `Crew` só era montado em
            # Python, ao lado de uma definição que já dizia o resto. Composto,
            # ele entra num degrau cujo `consome` é derivado dos blocos
            # (`consome_de`), e um Crew que não declara nada faria o degrau
            # inteiro ver o pool todo: o item de outro ramo entraria na
            # tripulação e sairia com proposta de um agente que não fala sobre
            # ele — caro e errado, sem erro nenhum.
            consome=frozenset().union(*(a.describe().consome for a in self.agents)),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        """Devolve `proposals`, NUNCA `resolutions`.

        Não é disciplina, é o tipo: `ResolverOutput.resolutions` simplesmente
        não é preenchido, e `WorkSet.without()` não aceita proposta.
        """
        propostas: list[Proposal] = []
        total = Cost.zero()
        modelo = self.agents[0].client.model

        for tarefa in self._tarefas(work):
            if total.microcents(modelo) > self.budget_microcents:
                # Mesma política do `Agent`: estourar o teto é evento
                # observável, não exceção. Abstém o resto do lote sem chamar
                # modelo nenhum e diz por quê em cada proposta.
                propostas.append(
                    self._abster(
                        tarefa.id,
                        "orçamento da tripulação esgotado",
                        Cost.zero(),
                        [
                            TraceEvent(
                                kind=TraceKind.OUTCOME,
                                detail={"motivo": "orçamento da tripulação"},
                            )
                        ],
                    )
                )
                continue
            p = self._um_item(tarefa)
            propostas.append(p)
            total = total + p.cost
        return ResolverOutput(proposals=propostas, cost=total)

    # -- montagem das tarefas ---------------------------------------------

    def _tarefas(self, work: WorkSet) -> list[AgentTask]:
        """As tarefas, derivadas do PRIMEIRO agente — e conferidas nos demais.

        Agentes de uma tripulação trabalham os mesmos itens por definição. Se
        as `units` deles divergissem, estariam resolvendo problemas diferentes
        e a resolução de conflito compararia coisas não relacionadas — um
        desacordo aparente entre respostas sobre perguntas distintas.
        """
        base = self.agents[0].spec.units(work)
        esperados = [t.id for t in base]
        for outro in self.agents[1:]:
            ids = [t.id for t in outro.spec.units(work)]
            if ids != esperados:
                raise ValueError(
                    f"tripulação {self.name!r}: {self.agents[0].name!r} produz "
                    f"{esperados} e {outro.name!r} produz {ids}. agentes de uma "
                    f"tripulação precisam trabalhar os MESMOS itens, ou o "
                    f"desacordo medido é entre respostas a perguntas diferentes"
                )
        return base

    def _um_item(self, tarefa: AgentTask) -> Proposal:
        if self.process is Process.HIERARCHICAL:
            return self._hierarquico(tarefa)
        return self._sequencial(tarefa)

    # -- sequencial --------------------------------------------------------

    def _sequencial(self, tarefa: AgentTask) -> Proposal:
        """Cada agente lê o quadro branco e escreve nele. É a cascata de novo,
        um nível abaixo — e por isso reusa o mesmo laço, não um novo."""
        contexto = SharedContext()
        colhidas: list[Proposal] = []
        custo = Cost.zero()
        trace: list[TraceEvent] = [
            TraceEvent(kind=TraceKind.ENTRADA, detail={"item": tarefa.id, "crew": self.name})
        ]
        modelo = self.agents[0].client.model

        for rodada in range(1, self.max_rounds + 1):
            antes = contexto
            for agente in self.agents:
                if custo.microcents(modelo) > self.budget_microcents:
                    trace.append(
                        TraceEvent(
                            kind=TraceKind.OUTCOME,
                            detail={"motivo": "orçamento da tripulação", "rodada": rodada},
                        )
                    )
                    return self._decidir(tarefa.id, colhidas, custo, trace, contexto)
                p = agente.investigar(self._enriquecer(tarefa, contexto))
                custo = custo + p.cost
                colhidas.append(p)
                # O trace do agente entra no do Crew, em ordem. Sem isto a
                # proposta final sai com o custo certo e SEM os eventos que o
                # produziram: o coletor não vê turno de LLM nem chamada de
                # ferramenta, a árvore mostra o Crew como uma caixa opaca, e
                # `waste.py` relata "nenhuma ferramenta foi chamada" numa
                # execução que chamou cinco.
                #
                # Foi exatamente assim que este defeito apareceu — não num
                # teste, mas no relatório de economia da primeira execução ao
                # vivo da tripulação.
                trace.extend(_sem_entrada(p.trace))
                trace.append(
                    TraceEvent(
                        kind=TraceKind.OUTCOME,
                        detail={
                            "agente": agente.name,
                            "rodada": rodada,
                            "tipo": p.tipo,
                            "confianca": p.confianca.value,
                        },
                    )
                )
                contexto = contexto.write(
                    agente.name,
                    _CHAVE,
                    f"{p.tipo} — {p.explicacao}",
                    round=rodada,
                )
            if contexto is antes:
                # Ninguém mudou o quadro branco nesta rodada. Continuar seria
                # pagar N turnos por rodada para o time concordar consigo
                # mesmo — o modo de falha que o §10.4 nomeia.
                trace.append(
                    TraceEvent(
                        kind=TraceKind.OUTCOME,
                        detail={"motivo": "quadro branco estável", "rodada": rodada},
                    )
                )
                break
        return self._decidir(tarefa.id, colhidas, custo, trace, contexto)

    def _enriquecer(self, tarefa: AgentTask, contexto: SharedContext) -> AgentTask:
        """O prompt do agente mais o que já foi escrito no quadro.

        O primeiro agente recebe a tarefa crua — enriquecer com um quadro vazio
        acrescentaria um cabeçalho inútil a todo primeiro turno, e o primeiro
        turno é o que a marcação de cache protege.
        """
        if not len(contexto):
            return tarefa
        return AgentTask(
            id=tarefa.id,
            prompt=(
                f"{tarefa.prompt}\n\n"
                f"--- o que a tripulação já concluiu ---\n"
                f"{contexto.render()}\n"
                f"--- fim ---\n"
                f"Considere o acima. Discordar é resposta válida."
            ),
        )

    # -- hierárquico -------------------------------------------------------

    def _hierarquico(self, tarefa: AgentTask) -> Proposal:
        """O gerente roteia; ele NÃO executa trabalho.

        Sem essa restrição, "hierárquico" vira "um agente grande com
        ferramentas caras", que é o modo de falha mais comum desse padrão.

        A implementação aqui mantém a restrição de forma estrutural: o gerente
        é chamado com a tarefa e o quadro branco, e o que ele produz é usado
        SÓ para escolher o worker — o `tipo` da proposta dele é descartado. Se
        ele resolvesse, o modo seria sequencial com um passo a mais.
        """
        assert self.manager is not None  # garantido no __post_init__
        custo = Cost.zero()
        trace: list[TraceEvent] = [
            TraceEvent(kind=TraceKind.ENTRADA, detail={"item": tarefa.id, "crew": self.name})
        ]
        # Idem no hierárquico: o trace do gerente e o do especialista entram
        # no do Crew.
        roteamento = self.manager.investigar(
            AgentTask(
                id=tarefa.id,
                prompt=(
                    f"{tarefa.prompt}\n\n"
                    f"--- especialistas disponíveis ---\n"
                    + "\n".join(
                        f"{a.name}: {a.describe().summary}" for a in self.agents
                    )
                    + "\n--- fim ---\n"
                    "Você NÃO resolve o item. Diga apenas qual especialista deve "
                    "recebê-lo, citando o nome exato dele na sua explicação."
                ),
            )
        )
        custo = custo + roteamento.cost
        trace.extend(_sem_entrada(roteamento.trace))
        escolhido = self._escolher(roteamento)
        trace.append(
            TraceEvent(
                kind=TraceKind.OUTCOME,
                detail={
                    "gerente": self.manager.name,
                    "roteou_para": escolhido.name,
                    # O tipo do gerente é registrado e DESCARTADO. Fica no
                    # trace para que dê para medir quantas vezes ele tentou
                    # resolver em vez de rotear — se for muito, o prompt dele
                    # está errado e isso é mensurável.
                    "tipo_descartado": roteamento.tipo,
                },
            )
        )
        contexto = SharedContext().write(
            self.manager.name, "roteamento", f"para {escolhido.name}"
        )
        final = escolhido.investigar(self._enriquecer(tarefa, contexto))
        custo = custo + final.cost
        trace.append(
            TraceEvent(
                kind=TraceKind.OUTCOME,
                detail={"agente": escolhido.name, "tipo": final.tipo},
            )
        )
        return Proposal(
            item_id=final.item_id,
            tipo=final.tipo,
            explicacao=final.explicacao,
            evidencia=final.evidencia,
            confianca=final.confianca,
            acao_sugerida=final.acao_sugerida,
            cost=custo,
            trace=[*trace, *_sem_entrada(final.trace)],
        )

    def _escolher(self, roteamento: Proposal) -> Agent:
        """Qual worker o gerente pediu, pelo nome citado na explicação.

        Sem ferramenta de delegação porque ela exigiria que o gerente tivesse
        um `ToolRegistry` montado pelo Crew, e um registro que o Crew injeta é
        um registro que o domínio não controla. Casar pelo nome é mais
        frágil — e por isso a queda é EXPLÍCITA: gerente que não cita ninguém
        cai no primeiro agente, e o trace registra que caiu.
        """
        texto = f"{roteamento.explicacao} {' '.join(roteamento.evidencia)}".lower()
        for agente in self.agents:
            if agente.name.lower() in texto:
                return agente
        return self.agents[0]

    # -- conflito ----------------------------------------------------------

    def _decidir(
        self,
        item_id: str,
        colhidas: list[Proposal],
        custo: Cost,
        trace: list[TraceEvent],
        contexto: SharedContext,
    ) -> Proposal:
        if not colhidas:
            return self._abster(item_id, "nenhum agente produziu proposta", custo, trace)

        arriscadas = [p for p in colhidas if p.tipo not in self.abstem_com]
        if not arriscadas:
            motivos = "; ".join(sorted({p.explicacao for p in colhidas}))
            return self._abster(
                item_id, f"toda a tripulação se absteve: {motivos}", custo, trace
            )

        tipos = {p.tipo for p in arriscadas}
        if len(tipos) == 1:
            return self._concordaram(item_id, arriscadas, custo, trace)

        trace.append(
            TraceEvent(
                kind=TraceKind.OUTCOME,
                detail={"desacordo": sorted(tipos), "politica": self.conflito.value},
            )
        )
        if self.conflito is Conflito.MAIORIA:
            return self._maioria(item_id, arriscadas, custo, trace)
        if self.conflito is Conflito.SINTETIZAR:
            return self._sintetizar(item_id, arriscadas, custo, trace, contexto)
        return self._desacordo_abstem(item_id, arriscadas, custo, trace)

    def _concordaram(
        self, item_id: str, arriscadas: list[Proposal], custo: Cost, trace: list[TraceEvent]
    ) -> Proposal:
        """Concordância une evidência e NÃO eleva confiança.

        Parece contraintuitivo e é o ponto mais importante deste módulo. No
        modo sequencial o agente 2 LEU a resposta do agente 1 antes de
        responder — eles não são independentes, então concordar é em parte
        ancoragem, não corroboração. Elevar a confiança aqui venderia como
        evidência aquilo que o próprio desenho do modo produz.

        A confiança final é a MENOR entre os que concordaram, pela mesma razão
        conservadora: quem viu menos e duvidou mais é o limite honesto.
        """
        evidencia: list[str] = []
        for p in arriscadas:
            for e in p.evidencia:
                if e not in evidencia:
                    evidencia.append(e)
        menor = min(arriscadas, key=lambda p: _ORDEM_CONFIANCA[p.confianca])
        base = arriscadas[-1]
        trace.append(
            TraceEvent(
                kind=TraceKind.OUTCOME,
                detail={
                    "acordo": base.tipo,
                    "agentes": len(arriscadas),
                    "confianca": menor.confianca.value,
                },
            )
        )
        return Proposal(
            item_id=item_id,
            tipo=base.tipo,
            explicacao=base.explicacao,
            evidencia=evidencia,
            confianca=menor.confianca,
            acao_sugerida=base.acao_sugerida,
            cost=custo,
            trace=trace,
        )

    def _desacordo_abstem(
        self, item_id: str, arriscadas: list[Proposal], custo: Cost, trace: list[TraceEvent]
    ) -> Proposal:
        """Desacordo vira abstenção COM as hipóteses na evidência.

        Descartar as hipóteses jogaria fora a parte cara: o humano que receber
        este item precisa saber que houve duas leituras plausíveis e quais
        foram, ou a tripulação custou dinheiro para produzir um "não sei" igual
        ao de um agente sozinho.
        """
        hipoteses = [f"{p.tipo}: {p.explicacao}" for p in arriscadas]
        return self._abster(
            item_id,
            f"tripulação dividida entre {sorted({p.tipo for p in arriscadas})}",
            custo,
            trace,
            evidencia=hipoteses,
        )

    def _maioria(
        self, item_id: str, arriscadas: list[Proposal], custo: Cost, trace: list[TraceEvent]
    ) -> Proposal:
        contagem: dict[str, int] = {}
        for p in arriscadas:
            contagem[p.tipo] = contagem.get(p.tipo, 0) + 1
        maior = max(contagem.values())
        vencedores = [t for t, n in contagem.items() if n == maior]
        if len(vencedores) > 1:
            # Empate por maioria é abstenção com passos extras; melhor dizer o
            # nome certo e preservar as hipóteses.
            return self._desacordo_abstem(item_id, arriscadas, custo, trace)
        escolhido = vencedores[0]
        return self._concordaram(
            item_id, [p for p in arriscadas if p.tipo == escolhido], custo, trace
        )

    def _sintetizar(
        self,
        item_id: str,
        arriscadas: list[Proposal],
        custo: Cost,
        trace: list[TraceEvent],
        contexto: SharedContext,
    ) -> Proposal:
        assert self.synthesizer is not None  # garantido no __post_init__
        sintese = self.synthesizer.investigar(
            AgentTask(
                id=item_id,
                prompt=(
                    "A tripulação discordou. Leia as conclusões e escreva a "
                    "resposta final.\n\n"
                    f"{contexto.render()}\n\n"
                    "Se as leituras forem igualmente plausíveis, não escolha: "
                    "dizer que não sabe é resposta válida."
                ),
            )
        )
        total = custo + sintese.cost
        trace.append(
            TraceEvent(
                kind=TraceKind.OUTCOME,
                detail={"sintetizador": self.synthesizer.name, "tipo": sintese.tipo},
            )
        )
        return Proposal(
            item_id=item_id,
            tipo=sintese.tipo,
            explicacao=sintese.explicacao,
            evidencia=sintese.evidencia or [p.explicacao for p in arriscadas],
            confianca=sintese.confianca,
            acao_sugerida=sintese.acao_sugerida,
            cost=total,
            trace=[*trace, *_sem_entrada(sintese.trace)],
        )

    def _abster(
        self,
        item_id: str,
        motivo: str,
        custo: Cost,
        trace: list[TraceEvent],
        evidencia: list[str] | None = None,
    ) -> Proposal:
        """O "não sei" da tripulação, no vocabulário do domínio.

        `abstem_com` é um conjunto porque um domínio pode ter mais de um jeito
        de não saber; para ESCREVER uma abstenção é preciso escolher um, e o
        critério é ordem estável — um `next(iter(frozenset))` daria rótulos
        diferentes entre execuções e quebraria o determinismo que o produto
        vende.
        """
        rotulo = sorted(self.abstem_com)[0]
        p = Proposal.abstencao(item_id, rotulo, motivo, custo, trace)
        if not evidencia:
            return p
        return Proposal(
            item_id=p.item_id,
            tipo=p.tipo,
            explicacao=p.explicacao,
            evidencia=evidencia,
            confianca=p.confianca,
            acao_sugerida=p.acao_sugerida,
            cost=p.cost,
            trace=p.trace,
        )


def _sem_entrada(trace: list[TraceEvent]) -> list[TraceEvent]:
    """O trace de um agente MENOS o marcador de entrada de item.

    `TraceKind.ENTRADA` é o que o coletor usa para abrir um span de ITEM. Cada
    agente emite o seu, e o Crew emite o dele — juntar tudo cru faz N+1 spans
    de ITEM para o mesmo item.

    Medido: com 50 casos e dois agentes, o relatório de economia imprimiu
    `29/71` — vinte e nove itens de setenta e um, num conjunto de cinquenta.
    Número impossível, e ele só apareceu porque a saída mostra o denominador.
    Uma métrica que imprimisse só a porcentagem teria escondido isto.

    Os eventos de LLM e de ferramenta ficam: são eles que atribuem custo.
    """
    return [e for e in trace if e.kind is not TraceKind.ENTRADA]


_ORDEM_CONFIANCA = {Confidence.BAIXA: 0, Confidence.MEDIA: 1, Confidence.ALTA: 2}
