"""`buscar_lancamentos`: lançamentos contábeis por valor, fornecedor ou documento."""

from typing import Any

from orchestrator.agent.tools.registry import ToolPermission, ToolSpec, tool_schema
from orchestrator.domains.reconciliation.agent.ferramentas.contexto import ToolContext, ledger_dict

_LIMITE_PADRAO = 10


def buscar_lancamentos(
    ctx: ToolContext,
    valor: int | None = None,
    fornecedor: str | None = None,
    documento: str | None = None,
    limite: int | None = None,
) -> list[dict[str, Any]]:
    """Lançamentos contábeis por valor líquido, fornecedor ou documento."""
    if valor is None and fornecedor is None and documento is None and limite is None:
        raise ValueError("buscar_lancamentos exige pelo menos um critério")

    # `limite or _LIMITE_PADRAO` seria armadilha: 0 é falsy e viraria 10, e um
    # limite negativo entraria na fatia como `achados[:-3]`, devolvendo tudo
    # menos os últimos três. Medido: limite=-3 devolveu 197 de 200 lançamentos —
    # exatamente o "vira o dataset inteiro no contexto" que esta guarda existe
    # para impedir.
    if limite is None:
        limite = _LIMITE_PADRAO
    if limite < 1:
        raise ValueError(f"limite deve ser pelo menos 1: {limite}")

    achados = [
        le
        for le in ctx.ledger
        if (valor is None or le.net_amount == valor)
        and (fornecedor is None or le.supplier == fornecedor)
        and (documento is None or le.document == documento)
    ]
    return [ledger_dict(le) for le in achados[:limite]]


_DESCRICAO = (
    "Busca lançamentos contábeis por valor líquido em centavos, fornecedor ou "
    "documento. Devolve no máximo `limite` resultados, ou 10 se `limite` for "
    "omitido. Enviar os quatro campos como null é erro."
)

SPEC = ToolSpec(
    name="buscar_lancamentos",
    description=_DESCRICAO,
    input_schema=tool_schema(
        "buscar_lancamentos",
        _DESCRICAO,
        {
            "valor": {"type": ["integer", "null"], "description": "valor líquido em centavos"},
            "fornecedor": {"type": ["string", "null"]},
            "documento": {"type": ["string", "null"]},
            # Sem `minimum`: a Messages API recusa a requisição inteira com
            # `tools.0.custom: For 'integer' type, property 'minimum' is not
            # supported`. A invariante não se perdeu — quem a garante é a função
            # acima, que levanta em `limite < 1` e tem o comentário de medição. O
            # schema só a ANUNCIA, em prosa.
            "limite": {
                "type": ["integer", "null"],
                "description": "máximo de resultados; pelo menos 1",
            },
        },
        ["valor", "fornecedor", "documento", "limite"],
    ),
    fn=buscar_lancamentos,
    permission=ToolPermission.READ_ONLY,
)
