"""Gravação e reprise de sessões do modelo.

A camada do meio dos três níveis de teste: grava-se uma vez contra a API real, e
aquilo vira teste determinístico e gratuito para sempre. Pega regressão no laço,
no parsing e nas ferramentas — não pega mudança de comportamento do modelo, que
é trabalho da avaliação ao vivo.
"""

import json
from pathlib import Path
from typing import Any

from orchestrator.agent.llm import LLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost


def _serializar(r: LLMResponse, model: str) -> str:
    return json.dumps(
        {
            "model": model,
            "text": r.text,
            "tool_calls": [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in r.tool_calls
            ],
            "cost": {
                "input_tokens": r.cost.input_tokens,
                "output_tokens": r.cost.output_tokens,
                "cached_tokens": r.cost.cached_tokens,
                # Sem este campo a reprise reportaria custo menor que o real em
                # toda gravação que tocou escrita de cache — Cost tem cinco
                # campos, e os cinco precisam sobreviver à ida e volta.
                "cache_creation_tokens": r.cost.cache_creation_tokens,
                "calls": r.cost.calls,
            },
        },
        ensure_ascii=False,
    )


def _desserializar(linha: str) -> tuple[str, LLMResponse]:
    d = json.loads(linha)
    return d["model"], LLMResponse(
        text=d["text"],
        tool_calls=[ToolCall(**c) for c in d["tool_calls"]],
        cost=Cost(**d["cost"]),
    )


class RecordingClient:
    """Repassa para o cliente interno e grava a resposta."""

    def __init__(self, inner: LLMClient, path: Path) -> None:
        self._inner = inner
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("", encoding="utf-8")

    @property
    def model(self) -> str:
        return self._inner.model

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        resposta = self._inner.complete(system=system, messages=messages, tools=tools)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(_serializar(resposta, self._inner.model) + "\n")
        return resposta


class ReplayClient:
    """Reproduz uma gravação, em ordem, sem tocar em rede nenhuma."""

    def __init__(self, path: Path) -> None:
        caminho = Path(path)
        if not caminho.exists():
            raise FileNotFoundError(f"gravação não encontrada: {caminho}")
        linhas = [
            linha
            for linha in caminho.read_text(encoding="utf-8").splitlines()
            if linha.strip()
        ]
        pares = [_desserializar(linha) for linha in linhas]
        self.model = pares[0][0] if pares else "desconhecido"
        self._respostas = [r for _, r in pares]
        self._indice = 0

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        assert self._indice < len(self._respostas), (
            f"a reprise tem {len(self._respostas)} turnos gravados, mas o laço "
            f"pediu o turno {self._indice + 1} — o comportamento mudou desde a gravação"
        )
        resposta = self._respostas[self._indice]
        self._indice += 1
        return resposta
