"""A costura do modelo.

Todo o resto do agente fala com esta interface, nunca com um SDK. É o que
permite testar o laço, o orçamento e a abstenção sem gastar um centavo, e o que
permite trocar de modelo sem tocar em lógica de domínio.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from orchestrator.kernel.cost import Cost


@dataclass(frozen=True)
class ToolCall:
    """Um pedido do modelo para executar uma ferramenta."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    cost: Cost
    # Blocos de conteúdo crus da resposta (texto, tool_use, thinking — o que
    # o modelo devolveu, na ordem em que devolveu). Precisa voltar VERBATIM
    # como turno do assistente na próxima chamada: é o único jeito de
    # preservar blocos de raciocínio (obrigatório em modelos com thinking
    # adaptativo) e de dar ao SDK real o mesmo objeto que ele emitiu. Lista
    # vazia por padrão — `FakeLLMClient` e `ReplayClient` não a preenchem, e o
    # investigador reconstrói um turno mínimo a partir de `text`/`tool_calls`
    # quando ela vem vazia.
    raw_content: list[Any] = field(default_factory=list)
    # Por que o modelo parou: "end_turn", "tool_use", "max_tokens", etc.
    # Ausente (None) só em resposta que nunca veio de uma API de verdade.
    stop_reason: str | None = None

    def __post_init__(self) -> None:
        # Resposta vazia sem pedido de ferramenta não é resposta. Deixar passar
        # faria o laço girar sem avançar.
        if not self.text and not self.tool_calls:
            raise ValueError("resposta sem texto e sem chamada de ferramenta")


def blocos_assistente(resposta: LLMResponse) -> list[Any]:
    """Blocos de conteúdo de um turno do assistente, para ecoar de volta.

    Devolve `raw_content` VERBATIM quando existe — inclui blocos de thinking,
    que a API exige de volta inalterados, e é o único jeito de dar ao SDK
    real o mesmo objeto que ele emitiu. `FakeLLMClient` e `ReplayClient`
    nunca preenchem `raw_content`; para esses, reconstrói um turno mínimo a
    partir de `text`/`tool_calls`, só para que os testes movidos a dublê
    continuem exercitando o laço.

    Compartilhada entre `Investigator` e `Entrevistador`: eram duas cópias
    quase idênticas até esta função existir, e uma correção crítica (o
    tool_use órfão de chamada paralela, Task 4 do grill) tinha sido aplicada
    numa cópia e não na outra — a prova de que duplicar este bloco custa
    caro. Não duplique de novo: qualquer terceiro laço de turnos deve
    importar daqui.
    """
    if resposta.raw_content:
        return resposta.raw_content
    blocos: list[Any] = []
    if resposta.text:
        blocos.append({"type": "text", "text": resposta.text})
    blocos.extend(
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
        for c in resposta.tool_calls
    )
    return blocos


class LLMClient(Protocol):
    """O que o agente precisa de um modelo, e nada além disso."""

    model: str

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...


class FakeLLMClient:
    """Cliente de teste: devolve respostas preparadas, em ordem, e registra o
    que recebeu.

    Acaba as respostas preparadas e ele levanta AssertionError de propósito —
    um laço que pede mais turnos do que o teste previu é laço descontrolado, e
    devolver algo vazio esconderia isso.

    O que ele NÃO garante: grava `messages` em `chamadas` só para inspeção do
    teste, mas nunca valida a forma delas. Ele prova a lógica do laço —
    orçamento, retry de formato, execução de ferramenta — nunca o protocolo de
    mensagens que o SDK real exige. Essa prova mora só em
    `test_anthropic_client.py`.
    """

    def __init__(
        self, respostas: list[LLMResponse], model: str = "claude-opus-5"
    ) -> None:
        # O modelo padrão é um de verdade, não "fake": o investigador consulta
        # `client.model` para calcular custo contra a tabela de preços, e um
        # nome inventado faria todo teste de orçamento levantar ValueError.
        self.model = model
        self._respostas = list(respostas)
        self.chamadas: list[dict[str, Any]] = []

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        self.chamadas.append({"system": system, "messages": messages, "tools": tools})
        assert self._respostas, (
            f"o laço pediu o turno {len(self.chamadas)} mas o teste preparou "
            f"apenas {len(self.chamadas) - 1}"
        )
        return self._respostas.pop(0)
