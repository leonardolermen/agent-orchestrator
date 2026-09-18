"""Camada L2: mesmo documento, com folga em valor e data.

Tolerância padrão vem do spec: 5 centavos e 3 dias úteis.
"""

from dataclasses import dataclass, field

from orchestrator.dates import business_days_between
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.models import PAYLOADS, LedgerEntry, banco, conciliacao, contabil


@dataclass
class ToleranceMatcher:
    max_cents: int = 5
    max_business_days: int = 3
    name: str = field(default="L2", init=False)
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        # Tolerância negativa não casaria nada e pareceria uma camada que
        # simplesmente não encontrou nada — falha silenciosa disfarçada de
        # resultado.
        if self.max_cents < 0:
            raise ValueError(f"max_cents não pode ser negativo: {self.max_cents}")
        if self.max_business_days < 0:
            raise ValueError(
                f"max_business_days não pode ser negativo: {self.max_business_days}"
            )

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary="mesmo documento, com folga de valor e dias úteis",
            payloads=PAYLOADS,
            consome=frozenset(PAYLOADS),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(resolutions=self._casar(work))

    def _casar(self, work: WorkSet) -> list[Resolution]:
        bank, ledger = banco(work), contabil(work)
        por_documento: dict[str, list[LedgerEntry]] = {}
        for le in ledger:
            if le.document is not None and le.cash_date is not None:
                por_documento.setdefault(le.document, []).append(le)

        resultados: list[Resolution] = []
        usados: set[str] = set()

        for be in bank:
            if be.document is None:
                continue

            for le in por_documento.get(be.document, []):
                if le.id in usados or le.cash_date is None:
                    continue

                diferenca = abs(abs(be.amount) - le.net_amount)
                dias = business_days_between(be.date, le.cash_date)
                if diferenca > self.max_cents or dias > self.max_business_days:
                    continue

                usados.add(le.id)
                resultados.append(
                    conciliacao(
                        work,
                        frozenset({be.id, le.id}),
                        produced_by=self.name,
                        rule=(
                            f"tolerância: até {self.max_cents} centavos e "
                            f"{self.max_business_days} dias úteis"
                        ),
                        evidence={
                            "documento": be.document,
                            "diferenca_centavos": diferenca,
                            "diferenca_dias_uteis": dias,
                        },
                    )
                )
                break

        return resultados
