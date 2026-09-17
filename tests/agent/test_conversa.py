"""O laço de turnos, sem saber o que é uma proposta.

Este arquivo é a prova de que a extração é genérica: nada aqui importa
`Proposal`. Se um teste daqui precisar dela, a extração falhou e o laço
continua sabendo o que o agente devolve.
"""

from orchestrator.agent.conversa import conversar
from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost


def _resposta(texto: str) -> LLMResponse:
    return LLMResponse(text=texto, tool_calls=[], cost=Cost(input_tokens=10, output_tokens=5))


def _sem_ferramentas() -> ToolRegistry:
    # Construtor posicional: `ToolRegistry([spec, ...], contexto=...)`.
    return ToolRegistry([])


def test_devolve_o_que_o_interpretador_produziu():
    """O laço não sabe o tipo de saída — devolve o que lhe derem."""
    cliente = FakeLLMClient([_resposta("ok")])

    r = conversar(
        client=cliente,
        tools=_sem_ferramentas(),
        system="s",
        item_id="i",
        prompt="p",
        max_turns=3,
        max_format_retries=2,
        budget_microcents=10_000_000,
        interpretar=lambda item, texto, custo, trace: {"item": item, "texto": texto},
        desistir=lambda item, motivo, custo, trace: {"desistiu": motivo},
    )

    assert r == {"item": "i", "texto": "ok"}


def test_interpretador_que_devolve_none_dispara_retry_de_formato():
    """`None` é "formato inválido, tente de novo" — nunca "desisti"."""
    cliente = FakeLLMClient([_resposta("lixo"), _resposta("bom")])
    vistos = []

    def interpretar(item, texto, custo, trace):
        vistos.append(texto)
        return None if texto == "lixo" else texto

    r = conversar(
        client=cliente, tools=_sem_ferramentas(), system="s", item_id="i", prompt="p",
        max_turns=3, max_format_retries=2, budget_microcents=10_000_000,
        interpretar=interpretar,
        desistir=lambda item, motivo, custo, trace: "DESISTIU",
    )

    assert vistos == ["lixo", "bom"]
    assert r == "bom"


def test_estourar_o_orcamento_desiste_com_o_custo_acumulado():
    cliente = FakeLLMClient([_resposta("ok")])
    capturado = {}

    def desistir(item, motivo, custo, trace):
        capturado["motivo"] = motivo
        capturado["custo"] = custo
        return "DESISTIU"

    r = conversar(
        client=cliente, tools=_sem_ferramentas(), system="s", item_id="i", prompt="p",
        max_turns=3, max_format_retries=2, budget_microcents=1,
        interpretar=lambda *a: "nunca chega aqui",
        desistir=desistir,
    )

    assert r == "DESISTIU"
    assert "orçamento" in capturado["motivo"]
    assert capturado["custo"] != Cost.zero()
