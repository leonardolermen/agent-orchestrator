"""Agent Orchestrator — runtime para trabalho inteligente.

Um workflow é uma cascata de tentativas ordenada por CUSTO: a regra de graça
primeiro, o agente depois, a tripulação depois, e o humano por último. O runtime
decide, por item, até onde subir — e registra por quê.

    from orchestrator import Agent, AgentSpec, Task, Tool, Workflow

    buscar = Tool(
        name="buscar_pedido",
        description="Busca um pedido de compra pelo número.",
        input_schema=tool_schema("buscar_pedido", "", {"numero": {"type": "string"}}, ["numero"]),
        fn=lambda numero: db.pedidos[numero],
    )

    triador = Agent(
        spec=AgentSpec(
            name="triador",
            system="Classifique a solicitação...",
            model="claude-sonnet-5",
            units=lambda work: [AgentTask(i.id, texto(i)) for i in work.of_kind("pedido")],
            parse=minha_leitura_do_json,
            abstain=meu_nao_sei,
        ),
        client=AnthropicClient(model="claude-sonnet-5"),  # agent.anthropic_client
        tools=ToolRegistry([buscar]),
    )

    wf = Workflow(
        id="compras",
        name="Triagem de compras",
        stages=(Task("classificar", cascade=[regra(), triador, revisor()]),),
    )

    run = execute(wf, pool_de_pedidos(pedidos))
    print(run.state, run.custo_total_microcents("claude-sonnet-5"))

**O que este `__init__` NÃO exporta, de propósito:** nada do domínio de
conciliação. Ela é a implementação de referência (§1.3), mora em
`orchestrator.domains.reconciliation`, e importá-la daqui faria todo usuário do framework
carregar a taxonomia de divergência fiscal brasileira.

**Estabilidade.** `0.x`: estes nomes podem mudar até o teste de generalidade
(§19.6) rodar contra um terceiro domínio escrito por outra pessoa. O que NÃO vai
mudar é a forma — cascata ordenada por custo, proposta que não resolve, política
que decide e registra.
"""

from orchestrator.agent.agent import Agent, AgentSpec, AgentTask
from orchestrator.agent.llm import FakeLLMClient, LLMClient, LLMResponse, ToolCall
from orchestrator.agent.tools.registry import (
    ToolPermission,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    tool_schema,
)
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, Task, WorkflowDefinition
from orchestrator.kernel.event import Event, EventBus, EventKind
from orchestrator.kernel.policy import (
    Autonomy,
    Budget,
    ExecutionPolicy,
    PolicyContext,
    PolicyDecision,
    Route,
)
from orchestrator.kernel.resolution import (
    Confidence,
    Proposal,
    Resolution,
    TraceEvent,
    TraceKind,
)
from orchestrator.kernel.resolver import Resolver, ResolverDescription, ResolverOutput
from orchestrator.kernel.run import Run, RunState
from orchestrator.kernel.source import Source
from orchestrator.kernel.trace import Span, SpanKind, SpanStatus, Trace
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime.engine import execute

# `Tool` é apelido de `ToolSpec`, e `Workflow` de `WorkflowDefinition`: os nomes
# longos dizem o que a coisa É (uma especificação, uma definição) e os curtos
# são o que alguém escreve. Apelido não é conceito novo — é a mesma razão de
# `Task()` ser açúcar sobre `Stage` (§8.2).
Tool = ToolSpec
Workflow = WorkflowDefinition

__all__ = [
    # agente
    "Agent",
    "AgentSpec",
    "AgentTask",
    "LLMClient",
    "LLMResponse",
    "FakeLLMClient",
    "ToolCall",
    # ferramentas
    "Tool",
    "ToolSpec",
    "ToolRegistry",
    "ToolPermission",
    "ToolResult",
    "tool_schema",
    # composição
    "Workflow",
    "WorkflowDefinition",
    "Stage",
    "Task",
    "Resolver",
    "ResolverOutput",
    "ResolverDescription",
    # trabalho e resultado
    "WorkItem",
    "WorkSet",
    "Resolution",
    "Proposal",
    "Confidence",
    # custo e política
    "Cost",
    "CostClass",
    "Budget",
    "ExecutionPolicy",
    "Autonomy",
    "Route",
    "PolicyContext",
    "PolicyDecision",
    # execução
    "execute",
    "Run",
    "RunState",
    "Source",
    # observação
    "Event",
    "EventBus",
    "EventKind",
    "Span",
    "SpanKind",
    "SpanStatus",
    "Trace",
    "TraceEvent",
    "TraceKind",
]
