"""Implementação real da costura, sobre o SDK da Anthropic.

Este é o único arquivo do projeto que conhece o SDK. Todo o resto fala com
`LLMClient`.
"""

from typing import Any

from orchestrator.agent.llm import LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost, modelo_precificado

_MAX_TOKENS = 2048

# Spec (tabela de tratamento de erro): timeout de LLM tenta de novo com
# backoff e desiste na 3ª tentativa. `max_retries=2` é 1 chamada inicial + 2
# retries do próprio SDK = 3 tentativas — o número mora aqui, explícito, em
# vez de ficar implícito no default de uma biblioteca de terceiros que pode
# mudar de versão para versão sem aviso.
_MAX_RETRIES = 2
# Um turno com ferramenta pode envolver raciocínio mais longo que uma resposta
# simples; 120s é generoso o bastante para isso sem deixar uma chamada travada
# pendurar uma divergência inteira por minutos.
_TIMEOUT_SEGUNDOS = 120.0


class AnthropicClient:
    """Traduz entre o SDK e a costura.

    `sdk` é injetável para teste. Em produção fica None e o cliente real é
    construído na primeira chamada — assim importar o módulo não exige
    credencial.
    """

    def __init__(self, model: str = "claude-opus-5", sdk: Any = None) -> None:
        if not modelo_precificado(model):
            raise ValueError(
                f"modelo sem preço conhecido: {model!r}. Sem preço não há custo, "
                f"e sem custo o produto não tem métrica."
            )
        self.model = model
        self._sdk = sdk

    def _cliente(self) -> Any:
        if self._sdk is None:
            import anthropic

            self._sdk = anthropic.Anthropic(
                timeout=_TIMEOUT_SEGUNDOS, max_retries=_MAX_RETRIES
            )
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
                # Tokens gastos para POPULAR o cache. Não aparecem em
                # input_tokens nem em cache_read_input_tokens, e custam mais que
                # entrada normal — ignorá-los subcontaria toda primeira chamada
                # de cada janela de cache.
                cache_creation_tokens=getattr(uso, "cache_creation_input_tokens", 0)
                or 0,
                calls=1,
            ),
            # Blocos crus, na ordem — inclui texto, tool_use e (em opus-5, que
            # roda thinking adaptativo por padrão) blocos de raciocínio. Viram
            # o turno do assistente verbatim na próxima chamada; reconstruir a
            # partir de `texto`/`chamadas` perderia justamente os blocos de
            # thinking, que a API exige de volta inalterados.
            raw_content=list(resposta.content),
            stop_reason=getattr(resposta, "stop_reason", None),
        )
