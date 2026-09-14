"""Modelo canônico de conciliação.

Cardinalidade: MatchResult vincula conjuntos a conjuntos, nunca par a par.
Exigido por PAGAMENTO_AGREGADO (1 crédito : N notas) e DEVOLUCAO_FUNDOS
(cadeia de 2-3 lançamentos bancários para 1 contábil). Ver spec 4.5.

Todos os valores monetários são int em centavos. Débitos bancários são
negativos, créditos positivos.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class BankEntry:
    """Lançamento de extrato bancário."""

    id: str
    date: date
    amount: int
    description: str
    counterparty: str | None = None
    document: str | None = None


@dataclass(frozen=True)
class LedgerEntry:
    """Lançamento contábil."""

    id: str
    accrual_date: date
    cash_date: date | None
    gross_amount: int
    net_amount: int
    account: str
    supplier: str
    cost_center: str | None = None
    document: str | None = None


@dataclass(frozen=True)
class MatchResult:
    """Vínculo determinístico entre conjuntos, com a justificativa."""

    bank_ids: frozenset[str]
    ledger_ids: frozenset[str]
    layer: str
    rule: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.bank_ids or not self.ledger_ids:
            raise ValueError("MatchResult exige pelo menos um id de cada lado")


@dataclass(frozen=True)
class Divergence:
    """O que nenhuma camada determinística resolveu."""

    id: str
    bank_ids: frozenset[str]
    ledger_ids: frozenset[str]

    def __post_init__(self) -> None:
        # Ao contrário de MatchResult, um lado vazio aqui é válido: um
        # lançamento contábil sem contrapartida bancária (ou vice-versa) é
        # uma divergência legítima de um lado só. Os dois vazios é que não
        # descrevem nada — nem um vínculo, nem uma sobra.
        if not self.bank_ids and not self.ledger_ids:
            raise ValueError("Divergence precisa de pelo menos um id")
