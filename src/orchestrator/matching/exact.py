"""Camada L1: documento, valor e data idênticos."""

from datetime import date

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.models import LedgerEntry, banco, conciliacao, contabil


class ExactMatcher:
    name = "L1"
    cost_class = CostClass.REGRA

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary="documento, valor e data coincidem exatamente",
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(resolutions=self._casar(work))

    def _casar(self, work: WorkSet) -> list[Resolution]:
        bank, ledger = banco(work), contabil(work)
        indice: dict[tuple[str, int, date], list[LedgerEntry]] = {}
        for le in ledger:
            if le.document is None or le.cash_date is None:
                continue
            indice.setdefault((le.document, le.net_amount, le.cash_date), []).append(le)

        resultados: list[Resolution] = []
        usados: set[str] = set()

        for be in bank:
            if be.document is None:
                continue
            chave = (be.document, abs(be.amount), be.date)
            candidatos = [le for le in indice.get(chave, []) if le.id not in usados]
            if not candidatos:
                continue

            escolhido = candidatos[0]
            usados.add(escolhido.id)
            resultados.append(
                conciliacao(
                    work,
                    frozenset({be.id, escolhido.id}),
                    produced_by=self.name,
                    rule="exato: documento, valor e data coincidem",
                    evidence={
                        "documento": be.document,
                        "valor": abs(be.amount),
                        "data": be.date.isoformat(),
                    },
                )
            )

        return resultados
