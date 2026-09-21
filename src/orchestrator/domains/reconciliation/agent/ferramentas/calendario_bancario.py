"""`calendario_bancario`: dias úteis entre duas datas."""

from datetime import date
from typing import Any

from orchestrator.agent.tools.registry import ToolPermission, ToolSpec, tool_schema
from orchestrator.domains.reconciliation.agent.ferramentas.contexto import ToolContext
from orchestrator.domains.reconciliation.dates import business_days_between


def _data(texto: str) -> date:
    """Converte ISO-8601 ou levanta. O modelo erra formato de data com
    frequência, e aceitar em silêncio produziria busca vazia inexplicável."""
    try:
        return date.fromisoformat(texto)
    except ValueError as erro:
        raise ValueError(f"data deve estar em AAAA-MM-DD: {texto!r}") from erro


def calendario_bancario(_ctx: ToolContext, de: str, ate: str) -> dict[str, Any]:
    """Dias úteis entre duas datas ISO. Ignora o contexto, explicitamente."""
    inicio, fim = _data(de), _data(ate)
    return {"de": de, "ate": ate, "dias_uteis": business_days_between(inicio, fim)}


_DESCRICAO = (
    "Conta dias úteis entre duas datas no formato AAAA-MM-DD. Fins de semana não "
    "contam."
)

SPEC = ToolSpec(
    name="calendario_bancario",
    description=_DESCRICAO,
    input_schema=tool_schema(
        "calendario_bancario",
        _DESCRICAO,
        {"de": {"type": "string"}, "ate": {"type": "string"}},
        ["de", "ate"],
    ),
    fn=calendario_bancario,
    permission=ToolPermission.READ_ONLY,
)
