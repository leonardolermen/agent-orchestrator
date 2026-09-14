"""Implementação real da costura, sobre o SDK da Anthropic.

Este é o único arquivo do projeto que conhece o SDK. Todo o resto fala com
`LLMClient`.
"""

from typing import Any

from orchestrator.agent.llm import LLMResponse, ToolCall
from orchestrator.agent.proposal import _PRECOS, Cost

_MAX_TOKENS = 2048


class AnthropicClient:
    """Traduz entre o SDK e a costura.

    `sdk` é injetável para teste. Em produção fica None e o cliente real é
    construído na primeira chamada — assim importar o módulo não exige
    credencial.
    """

    def __init__(self, model: str = "claude-opus-5", sdk: Any = None) -> None:
        if model not in _PRECOS:
            raise ValueError(
                f"modelo sem preço conhecido: {model!r}. Sem preço não há custo, "
                f"e sem custo o produto não tem métrica."
            )
        self.model = model
        self._sdk = sdk

    def _cliente(self) -> Any:
        if self._sdk is None:
            import anthropic

            self._sdk = anthropic.Anthropic()
        return self._sdk

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        resposta = self._cliente().messages.create(
            model=self.model,
            max_tokens=_MAX_TOKENS,
            # System e ferramentas são idênticos entre divergências; marcá-los
            # para cache é a maior economia isolada numa execução com centenas
            # de itens.
            system=[
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            messages=messages,
            tools=tools,
        )

        texto = "".join(b.text for b in resposta.content if b.type == "text")
        chamadas = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input))
            for b in resposta.content
            if b.type == "tool_use"
        ]
        uso = resposta.usage
        return LLMResponse(
            text=texto,
            tool_calls=chamadas,
            cost=Cost(
                input_tokens=getattr(uso, "input_tokens", 0),
                output_tokens=getattr(uso, "output_tokens", 0),
                cached_tokens=getattr(uso, "cache_read_input_tokens", 0) or 0,
                calls=1,
            ),
        )
