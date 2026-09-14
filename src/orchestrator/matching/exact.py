"""Camada L1: documento, valor e data idênticos."""

from datetime import date

from orchestrator.models import BankEntry, LedgerEntry, MatchResult


class ExactMatcher:
    layer = "L1"

    def match(self, bank: list[BankEntry], ledger: list[LedgerEntry]) -> list[MatchResult]:
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
                    layer=self.layer,
                    rule="exato: documento, valor e data coincidem",
                    evidence={
                        "documento": be.document,
                        "valor": abs(be.amount),
                        "data": be.date.isoformat(),
                    },
                )
            )

        return resultados
