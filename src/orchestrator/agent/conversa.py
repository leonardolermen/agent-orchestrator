"""O laço de turnos, sem saber o que sai dele.

`Agent.investigar` era este laço com dois pontos de domínio costurados no meio:
`spec.parse`, que vira proposta, e `spec.abstain`, que diz "não sei". Tudo à
volta — turnos, orçamento, execução de ferramenta, retry de formato, captura de
falha de API — é genérico e não sabe o que é uma `Proposal`.

Extraído porque a `Tarefa` precisa do MESMO laço com outros dois pontos:
um que vira item produzido e um que abstém. Duplicá-lo seria repetir o erro que
`blocos_assistente` já registra ter custado caro — uma correção crítica aplicada
numa cópia e esquecida na outra.

O que este módulo NÃO faz: decidir. Ele conversa e entrega o texto a quem sabe
interpretá-lo.
"""

import json
from collections.abc import Callable
from typing import Any, TypeVar

from orchestrator.agent.llm import LLMClient, blocos_assistente
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost
from orchestrator.kernel.resolution import TraceEvent, TraceKind

T = TypeVar("T")

# Como o texto final do modelo vira o item produzido. Devolve `None` quando o
# texto não é utilizável — e é esse `None` que dispara o retry de formato.
Interpretador = Callable[[str, str, Cost, list[TraceEvent]], T | None]

# Como o domínio diz "não sei". O segundo argumento é o MOTIVO da desistência,
# não o texto do modelo — a mesma forma de `Interpretador`, com um significado
# diferente no mesmo lugar.
Desistencia = Callable[[str, str, Cost, list[TraceEvent]], T]


def conversar(
    *,
    client: LLMClient,
    tools: ToolRegistry,
    system: str,
    item_id: str,
    prompt: str,
    max_turns: int,
    max_format_retries: int,
    budget_microcents: int,
    interpretar: Interpretador[T],
    desistir: Desistencia[T],
) -> T:
    """Um item, do prompt ao que `interpretar` produzir. O laço inteiro, para UM item."""
    mensagens: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    custo, tentativas_formato = Cost.zero(), 0
    esquemas = tools.schemas()
    trace: list[TraceEvent] = [
        TraceEvent(kind=TraceKind.ENTRADA, detail={"item": item_id})
    ]

    for turno in range(1, max_turns + 1):
        try:
            resposta = client.complete(
                system=system, messages=mensagens, tools=esquemas
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
            return desistir(
                item_id, f"falha de API ao investigar: {erro}", custo, trace
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

        if custo.microcents(client.model) > budget_microcents:
            trace.append(
                TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": "orçamento"})
            )
            return desistir(
                item_id, "orçamento do item esgotado", custo, trace
            )

        if resposta.tool_calls:
            resultados = [
                tools.call(c.name, c.arguments) for c in resposta.tool_calls
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

        proposta = interpretar(item_id, resposta.text, custo, trace)
        if proposta is not None:
            return proposta

        tentativas_formato += 1
        if tentativas_formato > max_format_retries:
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
    return desistir(
        item_id, "investigação encerrada sem conclusão utilizável", custo, trace
    )
