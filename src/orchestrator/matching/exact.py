"""Camada L1: documento, valor e data idênticos."""

from datetime import date

from orchestrator.models import BankEntry, LedgerEntry, MatchResult
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet


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
        return ResolverOutput(matches=self._casar(work.bank, work.ledger))

    def _casar(
        self, bank: list[BankEntry], ledger: list[LedgerEntry]
    ) -> list[MatchResult]:
        indice: dict[tuple[str, int, date], list[LedgerEntry]] = {}
        for le in ledger:
            if le.document is None or le.cash_date is None:
                continue
            indice.setdefault((le.document, le.net_amount, le.cash_date), []).append(le)

        resultados: list[MatchResult] = []
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
                MatchResult(
                    bank_ids=frozenset({be.id}),
                    ledger_ids=frozenset({escolhido.id}),
                    layer=self.name,
                    rule="exato: documento, valor e data coincidem",
                    evidence={
                        "documento": be.document,
                        "valor": abs(be.amount),
                        "data": be.date.isoformat(),
                    },
                )
            )

        return resultados
