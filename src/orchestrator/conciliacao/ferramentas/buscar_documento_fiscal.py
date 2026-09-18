"""`buscar_documento_fiscal`: o lançamento que carrega um número de documento."""

from typing import Any

from orchestrator.agent.tools.registry import ToolPermission, ToolSpec, tool_schema
from orchestrator.conciliacao.ferramentas.contexto import ToolContext, ledger_dict


def buscar_documento_fiscal(ctx: ToolContext, documento: str) -> dict[str, Any] | None:
    """Dados do lançamento que carrega este documento."""
    for le in ctx.ledger:
        if le.document == documento:
            return ledger_dict(le)
    return None


_DESCRICAO = "Busca o lançamento contábil de um documento fiscal pelo número."

SPEC = ToolSpec(
    name="buscar_documento_fiscal",
    description=_DESCRICAO,
    input_schema=tool_schema(
        "buscar_documento_fiscal",
        _DESCRICAO,
        {"documento": {"type": "string"}},
        ["documento"],
    ),
    fn=buscar_documento_fiscal,
    permission=ToolPermission.READ_ONLY,
)
