"""O que as ferramentas de conciliação podem enxergar, e nada além disso.

`ToolContext` era uma classe com CINCO métodos — uma ferramenta cada — e os
schemas moravam numa lista ao lado. O despacho ligava os dois por
`getattr(contexto, nome)`, de modo que a ferramenta existia em dois lugares:
a lógica aqui, a forma lá.

Com uma ferramenta por arquivo, os dois lados passam a morar juntos (a função e
o `ToolSpec` na mesma página), e o que sobra aqui são só os DADOS. Este módulo
não sabe mais quais ferramentas existem — o que é o ponto: acrescentar uma
deixou de exigir tocá-lo.
"""

from dataclasses import dataclass
from typing import Any

from orchestrator.models import BankEntry, LedgerEntry


@dataclass
class ToolContext:
    """Os dados da conciliação. O agente recebe só a divergência; tudo o mais
    ele pede por ferramenta, e sempre com limite — entregar o dataset inteiro
    seria custo e ruído."""

    bank: list[BankEntry]
    ledger: list[LedgerEntry]


def ledger_dict(le: LedgerEntry) -> dict[str, Any]:
    """A forma em que um lançamento chega ao modelo.

    Função de módulo e não método de `ToolContext`: nunca usou os dados do
    contexto, e ser método fazia parecer que usava. Três chamadores — duas
    ferramentas e o investigador, que monta o prompt inicial com a mesma forma
    que as ferramentas devolvem. Essa igualdade é deliberada: o modelo vê um
    lançamento de um jeito só.
    """
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
