"""O `Agent` genérico: o laço do `Investigator`, sem o domínio dentro.

Nenhuma linha de lógica nova. Turnos, orçamento em dois níveis, retry de
formato, execução de ferramenta com erro voltando ao modelo, abstenção como
saída — tudo preservado de `agent/investigator.py`, incluindo os comentários que
explicam por que cada guarda existe. O que mudou é que a CONFIGURAÇÃO saiu de
dentro do código.

**A distinção que torna isto possível.** O laço é genérico; o que é do domínio
é: (a) o system prompt, (b) as ferramentas, (c) como um item vira uma pergunta,
(d) como o texto do modelo vira uma proposta, (e) qual é o rótulo de "não sei".
Os cinco viram campos de `AgentSpec`, e nenhum deles é uma string mágica que o
laço precise interpretar.

**A unidade de trabalho do agente não é o `WorkItem`.** Na conciliação, um
agente investiga uma `Divergence` — que é derivada do pool, agrupa ids e tem
prefixo próprio. Em `domains/swe`, é a issue direto. Por isso `AgentSpec.units`
recebe o `WorkSet` e devolve `AgentTask`s: quem sabe o que é uma unidade de
investigação é o domínio.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from orchestrator.agent.conversa import conversar
from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import (
    Proposal,
    TraceEvent,
    TraceKind,
)
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet


@dataclass(frozen=True)
class AgentTask:
    """Uma unidade de investigação, do ponto de vista do agente.

    `id` é o que vai para `Proposal.item_id`; `prompt` é o que o modelo lê. O
    laço não sabe montar nenhum dos dois — quem monta é o domínio, em
    `AgentSpec.units`.
    """

    id: str
    prompt: str


# Como o texto final do modelo vira uma proposta. Devolve `None` quando o texto
# não é utilizável — e é esse `None` que dispara o retry de formato.
Parser = Callable[[str, str, Cost, list[TraceEvent]], Proposal | None]

# Como o domínio diz "não sei". `Proposal.abstencao` exige o `tipo`, e qual é o
# rótulo de não-saber é decisão do domínio (PR #6).
Abstainer = Callable[[str, str, Cost, list[TraceEvent]], Proposal]


@dataclass(frozen=True)
class AgentSpec:
    """A configuração de um agente. DADO, não comportamento.

    Congelado e serializável de propósito: é isso que permite `version` existir,
    e é `version` que o benchmark de M6 precisa para comparar prompt A com
    prompt B sem confundir os dois.
    """

    name: str
    system: str
    model: str
    units: Callable[[WorkSet], list[AgentTask]]
    parse: Parser
    abstain: Abstainer
    max_turns: int = 6
    max_format_retries: int = 2

    # Quais `WorkItem.kind` este agente pega do pool. Vazio = o pool inteiro.
    # Mora na SPEC porque o kind de um `AgenteDeclarado` é apagado na
    # construção — vira a closure de `units` — e `describe()` não teria de
    # onde lê-lo. A spec é a declaração; `describe()` a repassa.
    consome: frozenset[str] = frozenset()

    # CRITICAL 1 — derivação do padrão, não um chute. Medido em código, não
    # suposto (ver `test_orcamento_padrao_admite_um_turno_realista...`):
    #
    #   overhead fixo = len(system) + len(json.dumps(schemas))
    #                 ≈ 3553 chars ≈ 888 tokens de entrada,
    #   pela heurística grosseira de ~4 chars/token.
    #   saída realista por turno ≈ 200 tokens.
    #
    #   1º turno, sem cache, no modelo mais caro (opus-5: 500/2500 µ¢ por
    #   token de entrada/saída):  888*500 + 200*2500 = 944_000 µ¢
    #   turnos 2..6 com system+schemas cacheados (lidos a 0.1x):
    #     888*50 + 200*2500 = 544_400 µ¢ cada, x5 = 2_722_000 µ¢
    #   total: 3_666_000 µ¢, arredondado para cima com folga — a heurística é
    #   grosseira e o histórico cresce turno a turno, o que a conta não modela —
    #   para 4_000_000 µ¢ (US$ 0,04).
    budget_microcents: int = 4_000_000

    # I1 — teto por EXECUÇÃO, além do teto por item. O spec exige os dois
    # níveis. Cobre um lote de ~100 itens no pior caso, o que já é caro demais
    # para um operador não perceber antes de acontecer de novo.
    budget_total_microcents: int = 400_000_000

    @property
    def version(self) -> str:
        """sha256 curto de `(system, model, turnos)`.

        É a peça que falta para a `IdempotencyKey` do §6.4: hoje o agente pula
        qualquer item que já tenha proposta na fila, para SEMPRE — mudar o
        prompt ou trocar o modelo não invalida nada. Com `version` no lugar, a
        invalidação deixa de depender de alguém lembrar de apagar o arquivo.

        As ferramentas NÃO entram: elas vêm do `ToolRegistry`, que é do
        `Agent` e não da spec. Fechar isso é o PR #11.
        """
        bruto = json.dumps(
            [self.name, self.system, self.model, self.max_turns], ensure_ascii=False
        )
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:12]


@dataclass
class Agent:
    """Um `Resolver` de classe AGENTE. O laço genérico mais uma `AgentSpec`.

    Nunca levanta por causa do modelo. Toda falha — JSON quebrado, tipo
    inventado, ferramenta inexistente, orçamento estourado, turnos esgotados —
    vira abstenção registrada. Um agente que estoura no meio de um fechamento
    derruba o processo inteiro por causa de um item.
    """

    spec: AgentSpec
    client: LLMClient
    tools: ToolRegistry

    name: str = field(init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.spec.name)
        # `range(max_turns)` com max_turns <= 0 é vazio: o laço nunca chama o
        # modelo e a investigação inteira vira abstenção muda, sem custo e sem
        # trace de erro — um agente que não pode dar nem um turno não é agente,
        # é abstenção disfarçada de configuração válida.
        if self.spec.max_turns < 1:
            raise ValueError(f"max_turns precisa ser pelo menos 1: {self.spec.max_turns}")
        # Orçamento negativo faria a primeira comparação de custo já nascer
        # estourada: todo item abstém no primeiro turno, sem nunca chamar o
        # modelo, e pareceria um agente funcionando com orçamento zerado em vez
        # de uma configuração inválida.
        if self.spec.budget_microcents < 0:
            raise ValueError(
                f"budget_microcents não pode ser negativo: {self.spec.budget_microcents}"
            )
        if self.spec.budget_total_microcents < 0:
            raise ValueError(
                f"budget_total_microcents não pode ser negativo: "
                f"{self.spec.budget_total_microcents}"
            )
        # Modelo sem preço conhecido não é abstenção, é erro de configuração.
        # Abster em todo item gastaria a execução inteira sem produzir nada, e
        # o custo — métrica central do produto — ficaria incalculável. Falhar
        # aqui, uma vez, é o comportamento certo.
        Cost.zero().microcents(self.client.model)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=f"agente {self.spec.model}",
            model=self.spec.model,
            consome=self.spec.consome,
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        """Investiga o que sobrou. NUNCA devolve `resolutions`.

        Proposta não resolve — e aqui isso não é disciplina, é o tipo:
        `ResolverOutput.resolutions` simplesmente não é preenchido, e
        `WorkSet.without()` não aceita proposta.
        """
        propostas, total = [], Cost.zero()
        for tarefa in self.spec.units(work):
            if total.microcents(self.client.model) > self.spec.budget_total_microcents:
                # I1: estourar o teto da EXECUÇÃO é evento observável, não
                # exceção — abstém o restante do lote sem nem chamar o modelo,
                # e registra por quê em cada proposta.
                trace = [
                    TraceEvent(
                        kind=TraceKind.OUTCOME, detail={"motivo": "orçamento total"}
                    )
                ]
                propostas.append(
                    self.spec.abstain(
                        tarefa.id,
                        "orçamento total da execução esgotado",
                        Cost.zero(),
                        trace,
                    )
                )
                continue
            p = self.investigar(tarefa)
            propostas.append(p)
            total = total + p.cost
        return ResolverOutput(proposals=propostas, cost=total)

    def investigar(self, tarefa: AgentTask) -> Proposal:
        """Um item, do prompt à proposta.

        O laço mora em `conversa.conversar` desde a extração: aqui ficam só os
        dois pontos que sabem o que é uma proposta. Público desde o M8, porque
        o `Crew` roda o mesmo laço com o prompt enriquecido pelo
        `SharedContext` — e um sublinhado que dois módulos ignoram não protege
        nada, só esconde quem depende de quê.
        """
        return conversar(
            client=self.client,
            tools=self.tools,
            system=self.spec.system,
            item_id=tarefa.id,
            prompt=tarefa.prompt,
            max_turns=self.spec.max_turns,
            max_format_retries=self.spec.max_format_retries,
            budget_microcents=self.spec.budget_microcents,
            interpretar=self.spec.parse,
            desistir=self.spec.abstain,
        )
