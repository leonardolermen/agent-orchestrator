"""`calcular_retencao`: retenção na fonte, exata e testável.

É ferramenta e não raciocínio do modelo de propósito: cálculo fiscal precisa
ser exato, e um LLM que soma de cabeça erra em silêncio.
"""

from orchestrator.agent.tools.registry import ToolPermission, ToolSpec, tool_schema
from orchestrator.conciliacao.ferramentas.contexto import ToolContext
from orchestrator.tax import calcular_retencao as _calcular_retencao


def calcular_retencao(_ctx: ToolContext, bruto: int, aliquota_bp: int) -> int:
    """Retenção em centavos, truncada. Determinística por construção.

    Ignora o contexto — não precisa de dado nenhum —, e o ignora
    EXPLICITAMENTE: a assinatura `fn(contexto, **args)` é uniforme para todas as
    ferramentas, porque variável exigiria introspecção no despacho (ver
    `ToolSpec.fn`).
    """
    return _calcular_retencao(bruto, aliquota_bp)


_DESCRICAO = (
    "Calcula retenção na fonte em centavos sobre um valor bruto. A alíquota vai "
    "em basis points: 500 significa 5%. Use esta ferramenta em vez de calcular "
    "de cabeça."
)

SPEC = ToolSpec(
    name="calcular_retencao",
    description=_DESCRICAO,
    input_schema=tool_schema(
        "calcular_retencao",
        _DESCRICAO,
        {
            "bruto": {"type": "integer", "description": "valor bruto em centavos"},
            "aliquota_bp": {"type": "integer", "description": "alíquota em basis points"},
        },
        ["bruto", "aliquota_bp"],
    ),
    fn=calcular_retencao,
    permission=ToolPermission.READ_ONLY,
)
