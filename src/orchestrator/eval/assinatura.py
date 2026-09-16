"""O investigador movido a assinatura, para avaliação — nunca para produção.

Por que existe: medir a qualidade do agente exige chamá-lo de verdade, e o
caminho pago depende de crédito na Console. Este caminho usa o processo local
do Claude Code, que roda na assinatura do desenvolvedor.

**O que ele NÃO substitui.** Ele não exercita `anthropic_client.py`: o
protocolo de ferramentas da Messages API — os blocos `tool_result` casados por
`tool_use_id`, o eco do turno do assistente — continua sem prova por aqui. O
critical C2 do plano 2 só fecha com uma chamada pelo caminho pago.

**Limite de uso.** A documentação do Agent SDK é explícita: oferecer o login ou
os limites da assinatura dentro de um produto para terceiros exige aprovação
prévia da Anthropic. Este módulo é ferramenta de avaliação do próprio
desenvolvedor, fica atrás do extra opcional `[assinatura]`, e não entra em
nenhuma definição de workflow servida pela API.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from orchestrator.agent.investigator import (
    SYSTEM,
    descrever_divergencia,
    interpretar_proposta,
)
from orchestrator.agent.proposal import Proposal, TraceEvent, TraceKind
from orchestrator.agent.tools import TOOL_SCHEMAS, ToolContext
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.work import WorkSet
from orchestrator.models import divergencias
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput

_SERVIDOR = "conciliacao"

# As built-in do Claude Code vêm junto com o harness. O investigador é
# somente-leitura sobre o dataset (spec pai §4.2) e não pode ganhar acesso ao
# disco de brinde só porque trocamos de laço.
_PROIBIDAS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"]


def _qualificado(nome: str) -> str:
    """O nome pelo qual o agente enxerga a ferramenta no servidor MCP."""
    return f"mcp__{_SERVIDOR}__{nome}"


def _montar_servidor(context: ToolContext) -> Any:
    """Expõe as MESMAS cinco ferramentas, com os MESMOS schemas.

    `TOOL_SCHEMAS` é reusado verbatim — o decorador aceita JSON Schema
    completo. Se os dois caminhos declarassem contratos diferentes, comparar o
    agente pago com o agente por assinatura não mediria o agente, mediria a
    diferença entre as duas declarações.
    """
    from claude_agent_sdk import create_sdk_mcp_server, tool

    def _adaptar(esquema: dict[str, Any]):
        nome = esquema["name"]
        metodo = getattr(context, nome)

        @tool(nome, esquema["description"], esquema["input_schema"])
        async def _handler(args: dict[str, Any]) -> dict[str, Any]:
            # Mesma regra do laço pago: erro de ferramenta volta ao modelo como
            # texto, nunca como exceção — o modelo se corrige, o processo não.
            try:
                argumentos = {k: v for k, v in args.items() if v is not None}
                resultado = metodo(**argumentos)
            except Exception as erro:  # noqa: BLE001
                resultado = {"erro": str(erro)}
            texto = json.dumps(resultado, ensure_ascii=False, default=str)
            return {"content": [{"type": "text", "text": texto}]}

        return _handler

    return create_sdk_mcp_server(
        name=_SERVIDOR, version="1.0.0", tools=[_adaptar(e) for e in TOOL_SCHEMAS]
    )


@dataclass
class InvestigadorAssinatura:
    """Um `Resolver` como qualquer outro — é a cascata que torna isso barato."""

    context: ToolContext
    max_turns: int = 6

    name: str = field(default="investigador", init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

    # `cost_by_resolver` distingue chave ausente ("não rodou") de `Cost.zero()`
    # ("rodou e foi de graça"). Uma execução por assinatura não é nenhuma das
    # duas: ela consome, só não tem preço por chamada. Esta flag existe para o
    # relatório não imprimir US$ 0,00 e passar por medição.
    custo_mensuravel: bool = field(default=False, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary="investiga o que as regras não resolveram, via assinatura (avaliação)",
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        propostas = [self._uma(d) for d in divergencias(work)]
        return ResolverOutput(proposals=propostas, cost=Cost.zero())

    def _uma(self, divergencia: Any) -> Proposal:
        trace: list[TraceEvent] = [
            TraceEvent(kind=TraceKind.ENTRADA, detail={"divergencia": divergencia.id})
        ]
        try:
            texto, detalhe = asyncio.run(self._perguntar(divergencia))
        except Exception as erro:  # noqa: BLE001
            # Mesma política do caminho pago: falha de infraestrutura vira
            # abstenção registrada, nunca derruba o lote.
            trace.append(TraceEvent(kind=TraceKind.ERRO, detail={"erro": str(erro)}))
            return Proposal.abstencao(
                divergencia.id, f"falha ao investigar via assinatura: {erro}",
                Cost.zero(), trace,
            )

        trace.append(TraceEvent(kind=TraceKind.LLM, detail=detalhe))
        proposta = interpretar_proposta(divergencia.id, texto, Cost.zero(), trace)
        if proposta is not None:
            return proposta
        trace.append(
            TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": "sem conclusão"})
        )
        return Proposal.abstencao(
            divergencia.id, "investigação encerrada sem conclusão utilizável",
            Cost.zero(), trace,
        )

    async def _perguntar(self, divergencia: Any) -> tuple[str, dict[str, Any]]:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        opcoes = ClaudeAgentOptions(
            system_prompt=SYSTEM,
            mcp_servers={_SERVIDOR: _montar_servidor(self.context)},
            allowed_tools=[_qualificado(e["name"]) for e in TOOL_SCHEMAS],
            disallowed_tools=_PROIBIDAS,
            max_turns=self.max_turns,
            permission_mode="bypassPermissions",
            # Sem isto o SDK carrega skills, comandos e memória de `~/.claude/`
            # e do `.claude/` do projeto. Numa AVALIAÇÃO isso é contaminação: o
            # número medido passaria a depender da configuração pessoal de quem
            # rodou, e não seria comparável com o caminho pago nem entre
            # máquinas.
            setting_sources=[],
        )

        texto, detalhe = "", {}
        async for mensagem in query(
            prompt=descrever_divergencia(self.context, divergencia), options=opcoes
        ):
            if isinstance(mensagem, AssistantMessage):
                bloco = "".join(
                    b.text for b in mensagem.content if isinstance(b, TextBlock)
                )
                if bloco.strip():
                    texto = bloco
            elif isinstance(mensagem, ResultMessage):
                if isinstance(mensagem.result, str) and mensagem.result.strip():
                    texto = mensagem.result
                detalhe = {
                    "turnos": mensagem.num_turns,
                    "stop_reason": mensagem.stop_reason,
                    # O que a execução TERIA custado a preço de API. Não é
                    # fatura: na assinatura o custo marginal é zero. Vai no
                    # rastro rotulado como estimativa, nunca em `Cost`.
                    "custo_estimado_usd": mensagem.total_cost_usd,
                }
        return texto, detalhe
