"""`historico_fornecedor`: o padrão de pagamento de um fornecedor."""

from typing import Any

from orchestrator.agent.tools.registry import ToolPermission, ToolSpec, tool_schema
from orchestrator.conciliacao.ferramentas.contexto import ToolContext


def historico_fornecedor(ctx: ToolContext, fornecedor: str) -> dict[str, Any]:
    """Padrão histórico de pagamento do fornecedor."""
    dele = [le for le in ctx.ledger if le.supplier == fornecedor]
    return {
        "fornecedor": fornecedor,
        "quantidade": len(dele),
        "valor_total": sum(le.net_amount for le in dele),
        "contas_usadas": sorted({le.account for le in dele}),
    }


_DESCRICAO = (
    "Padrão histórico de pagamento de um fornecedor: quantidade de lançamentos, "
    "valor total e contas usadas."
)

SPEC = ToolSpec(
    name="historico_fornecedor",
    description=_DESCRICAO,
    input_schema=tool_schema(
        "historico_fornecedor",
        _DESCRICAO,
        {"fornecedor": {"type": "string"}},
        ["fornecedor"],
    ),
    fn=historico_fornecedor,
    permission=ToolPermission.READ_ONLY,
)
