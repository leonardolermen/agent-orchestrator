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
from typing import Any

from orchestrator.agent.llm import LLMClient, blocos_assistente
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
        """Um item, do prompt à proposta. O laço inteiro, para UMA tarefa.

        Público desde o M8. Era `_uma`, e `resolve` era o único chamador — até
        o `Crew` precisar rodar o mesmo laço com o prompt enriquecido pelo
        `SharedContext`. A alternativa era o Crew chamar `resolve` por agente,
        mas aí `AgentSpec.units` remontaria o prompt do payload e não haveria
        onde injetar o que os agentes anteriores escreveram.

        Tornar a costura pública é mais honesto que um Crew chamando `_uma` de
        outro módulo: um sublinhado que dois módulos ignoram não protege nada,
        só esconde quem depende de quê.
        """
        mensagens: list[dict[str, Any]] = [{"role": "user", "content": tarefa.prompt}]
        custo, tentativas_formato = Cost.zero(), 0
        esquemas = self.tools.schemas()
        trace: list[TraceEvent] = [
            TraceEvent(kind=TraceKind.ENTRADA, detail={"item": tarefa.id})
        ]

        for turno in range(1, self.spec.max_turns + 1):
            try:
                resposta = self.client.complete(
                    system=self.spec.system, messages=mensagens, tools=esquemas
                )
            except Exception as erro:  # noqa: BLE001
                # A captura envolve SÓ a chamada ao modelo, de propósito.
                # Alargá-la para o corpo do turno inteiro transformaria bug do
                # próprio agente — um AttributeError, um nome errado — em
                # abstenção plausível com suíte verde, que é a falha oposta e
                # pior da que esta guarda previne.
                #
                # Timeout, rede caída, 500 da API. O SDK já tenta de novo por
                # conta própria; se chegou aqui, acabou. Abster é a saída
                # certa: derrubar o processo inteiro por causa de um item
                # transformaria falha de rede em trabalho não entregue.
                trace.append(
                    TraceEvent(
                        kind=TraceKind.ERRO, detail={"turno": turno, "erro": str(erro)}
                    )
                )
                trace.append(
                    TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": "falha de api"})
                )
                return self.spec.abstain(
                    tarefa.id, f"falha de API ao investigar: {erro}", custo, trace
                )

            custo = custo + resposta.cost
            trace.append(
                TraceEvent(
                    kind=TraceKind.LLM,
                    detail={
                        "turno": turno,
                        "tokens_entrada": resposta.cost.input_tokens,
                        "tokens_saida": resposta.cost.output_tokens,
                        "ferramentas_pedidas": [c.name for c in resposta.tool_calls],
                        # I8: truncamento (max_tokens), recusa e falha de rede
                        # são três problemas operacionais diferentes que sem
                        # este campo aparecem idênticos.
                        "stop_reason": resposta.stop_reason,
                    },
                )
            )

            if custo.microcents(self.client.model) > self.spec.budget_microcents:
                trace.append(
                    TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": "orçamento"})
                )
                return self.spec.abstain(
                    tarefa.id, "orçamento do item esgotado", custo, trace
                )

            if resposta.tool_calls:
                resultados = [
                    self.tools.call(c.name, c.arguments) for c in resposta.tool_calls
                ]
                for chamada, r in zip(resposta.tool_calls, resultados, strict=True):
                    trace.append(
                        TraceEvent(
                            kind=TraceKind.TOOL,
                            detail={
                                "nome": chamada.name,
                                "argumentos": chamada.arguments,
                                # I2: o spec exige argumento E retorno no
                                # rastro — sem o retorno, uma auditoria não
                                # sabe o que a ferramenta respondeu.
                                "resultado": r.para_modelo(),
                                # Novo com o registry: latência por chamada.
                                "duracao_ms": r.duration_ms,
                            },
                        )
                    )
                mensagens.append(
                    {"role": "assistant", "content": blocos_assistente(resposta)}
                )
                # UM `tool_result` por `tool_use`, na mesma ordem: a Messages
                # API exige isso, e uma chamada paralela que recebesse só um
                # deixaria a(s) outra(s) órfã(s) e a PRÓXIMA chamada voltaria
                # com 400 (CRITICAL 2, defeito 2).
                mensagens.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": chamada.id,
                                "content": json.dumps(
                                    r.para_modelo(), ensure_ascii=False, default=str
                                ),
                            }
                            for chamada, r in zip(
                                resposta.tool_calls, resultados, strict=True
                            )
                        ],
                    }
                )
                continue

            proposta = self.spec.parse(tarefa.id, resposta.text, custo, trace)
            if proposta is not None:
                return proposta

            tentativas_formato += 1
            if tentativas_formato > self.spec.max_format_retries:
                break
            mensagens.append({"role": "assistant", "content": resposta.text})
            mensagens.append(
                {
                    "role": "user",
                    "content": "Resposta inválida. Responda APENAS o objeto JSON pedido.",
                }
            )

        trace.append(
            TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": "sem conclusão"})
        )
        return self.spec.abstain(
            tarefa.id, "investigação encerrada sem conclusão utilizável", custo, trace
        )
