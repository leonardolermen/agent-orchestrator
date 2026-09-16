"""As ferramentas do agente investigador.

TODAS são somente-leitura. O agente não escreve em lugar nenhum — ele produz
uma proposta, e quem escreve é o humano ao aprovar. Isso elimina deste plano
compensação, idempotência e rollback.

`calcular_retencao` é ferramenta e não raciocínio do modelo de propósito:
cálculo fiscal precisa ser exato e testável.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from orchestrator.agent.tools.registry import (
    ToolPermission,
    ToolRegistry,
    ToolSpec,
    tool_schema,
)
from orchestrator.dates import business_days_between
from orchestrator.models import BankEntry, LedgerEntry
from orchestrator.tax import calcular_retencao as _calcular_retencao

_LIMITE_PADRAO = 10


def _data(texto: str) -> date:
    """Converte ISO-8601 ou levanta. O modelo erra formato de data com
    frequência, e aceitar em silêncio produziria busca vazia inexplicável."""
    try:
        return date.fromisoformat(texto)
    except ValueError as erro:
        raise ValueError(f"data deve estar em AAAA-MM-DD: {texto!r}") from erro


@dataclass
class ToolContext:
    """O que as ferramentas podem enxergar.

    O agente recebe apenas a divergência; tudo o mais ele pede por aqui, e
    sempre com limite. Entregar o dataset inteiro seria custo e ruído.
    """

    bank: list[BankEntry]
    ledger: list[LedgerEntry]

    def buscar_lancamentos(
        self,
        valor: int | None = None,
        fornecedor: str | None = None,
        documento: str | None = None,
        limite: int | None = None,
    ) -> list[dict[str, Any]]:
        """Lançamentos contábeis por valor líquido, fornecedor ou documento."""
        if valor is None and fornecedor is None and documento is None and limite is None:
            raise ValueError("buscar_lancamentos exige pelo menos um critério")

        # `limite or _LIMITE_PADRAO` seria armadilha: 0 é falsy e viraria 10, e
        # um limite negativo entraria na fatia como `achados[:-3]`, devolvendo
        # tudo menos os últimos três. Medido: limite=-3 devolveu 197 de 200
        # lançamentos — exatamente o "vira o dataset inteiro no contexto" que
        # esta guarda existe para impedir.
        if limite is None:
            limite = _LIMITE_PADRAO
        if limite < 1:
            raise ValueError(f"limite deve ser pelo menos 1: {limite}")

        achados = [
            le
            for le in self.ledger
            if (valor is None or le.net_amount == valor)
            and (fornecedor is None or le.supplier == fornecedor)
            and (documento is None or le.document == documento)
        ]
        return [self.ledger_dict(le) for le in achados[:limite]]

    def buscar_documento_fiscal(self, documento: str) -> dict[str, Any] | None:
        """Dados do lançamento que carrega este documento."""
        for le in self.ledger:
            if le.document == documento:
                return self.ledger_dict(le)
        return None

    def historico_fornecedor(self, fornecedor: str) -> dict[str, Any]:
        """Padrão histórico de pagamento do fornecedor."""
        dele = [le for le in self.ledger if le.supplier == fornecedor]
        return {
            "fornecedor": fornecedor,
            "quantidade": len(dele),
            "valor_total": sum(le.net_amount for le in dele),
            "contas_usadas": sorted({le.account for le in dele}),
        }

    def calcular_retencao(self, bruto: int, aliquota_bp: int) -> int:
        """Retenção em centavos, truncada. Determinística por construção."""
        return _calcular_retencao(bruto, aliquota_bp)

    def calendario_bancario(self, de: str, ate: str) -> dict[str, Any]:
        """Dias úteis entre duas datas ISO."""
        inicio, fim = _data(de), _data(ate)
        return {"de": de, "ate": ate, "dias_uteis": business_days_between(inicio, fim)}

    @staticmethod
    def ledger_dict(le: LedgerEntry) -> dict[str, Any]:
        return {
            "id": le.id,
            "documento": le.document,
            "fornecedor": le.supplier,
            "bruto": le.gross_amount,
            "liquido": le.net_amount,
            "competencia": le.accrual_date.isoformat(),
            "caixa": le.cash_date.isoformat() if le.cash_date else None,
            "conta": le.account,
        }


def _spec(
    contexto: ToolContext,
    nome: str,
    descricao: str,
    props: dict[str, Any],
    obrigatorios: list[str],
) -> ToolSpec:
    """Uma entrada do registro, com o método do contexto JÁ LIGADO.

    `fn=getattr(contexto, nome)` é o que mata o join frágil: antes o despacho
    era `getattr(self.context, c.name)` cruzado com
    `{s["name"] for s in TOOL_SCHEMAS}` — duas listas paralelas, e uma
    ferramenta podia existir num lado e não no outro. Aqui o schema que o
    modelo vê e a função que roda saem da MESMA linha. Se o nome não existir no
    contexto, `getattr` levanta no REGISTRO, não numa chamada do modelo.

    Todas são `READ_ONLY`, e é por isso que este plano não tem compensação,
    idempotência nem rollback (§6.5). A primeira que escrever vai precisar
    declarar a compensadora, e o registry recusa se não declarar.
    """
    return ToolSpec(
        name=nome,
        description=descricao,
        input_schema=tool_schema(nome, descricao, props, obrigatorios),
        fn=getattr(contexto, nome),
        permission=ToolPermission.READ_ONLY,
    )


def registry_de(contexto: ToolContext) -> ToolRegistry:
    """As cinco ferramentas do investigador de conciliação."""
    return ToolRegistry([_spec(contexto, *args) for args in _FERRAMENTAS])


_FERRAMENTAS: list[tuple[str, str, dict[str, Any], list[str]]] = [
    (
        "buscar_lancamentos",
        "Busca lançamentos contábeis por valor líquido em centavos, fornecedor "
        "ou documento. Devolve no máximo `limite` resultados, ou 10 se `limite` "
        "for omitido. Enviar os quatro campos como null é erro.",
        {
            "valor": {"type": ["integer", "null"], "description": "valor líquido em centavos"},
            "fornecedor": {"type": ["string", "null"]},
            "documento": {"type": ["string", "null"]},
            "limite": {
                "type": ["integer", "null"],
                "minimum": 1,
                "description": "máximo de resultados; pelo menos 1",
            },
        },
        ["valor", "fornecedor", "documento", "limite"],
    ),
    (
        "buscar_documento_fiscal",
        "Busca o lançamento contábil de um documento fiscal pelo número.",
        {"documento": {"type": "string"}},
        ["documento"],
    ),
    (
        "historico_fornecedor",
        "Padrão histórico de pagamento de um fornecedor: quantidade de "
        "lançamentos, valor total e contas usadas.",
        {"fornecedor": {"type": "string"}},
        ["fornecedor"],
    ),
    (
        "calcular_retencao",
        "Calcula retenção na fonte em centavos sobre um valor bruto. A alíquota "
        "vai em basis points: 500 significa 5%. Use esta ferramenta em vez de "
        "calcular de cabeça.",
        {
            "bruto": {"type": "integer", "description": "valor bruto em centavos"},
            "aliquota_bp": {"type": "integer", "description": "alíquota em basis points"},
        },
        ["bruto", "aliquota_bp"],
    ),
    (
        "calendario_bancario",
        "Conta dias úteis entre duas datas no formato AAAA-MM-DD. Fins de "
        "semana não contam.",
        {"de": {"type": "string"}, "ate": {"type": "string"}},
        ["de", "ate"],
    ),
]


# Os schemas que o modelo vê, DERIVADOS do registro em vez de escritos ao lado
# dele. É a metade do join frágil que sobrevive por ser consumida por quem não
# tem um `ToolContext` na mão: o servidor MCP de `eval/assinatura.py` monta as
# ferramentas a partir da forma, e liga a função por conta própria.
#
# O contexto vazio é seguro aqui porque o schema NÃO depende do conteúdo do
# contexto — só dos nomes e assinaturas, que são do módulo. Se algum dia
# depender, esta linha vira uma função e o chamador passa o contexto dele.
TOOL_SCHEMAS: list[dict[str, Any]] = registry_de(ToolContext([], [])).schemas()
