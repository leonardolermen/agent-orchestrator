"""O que ainda não foi resolvido quando um resolver é chamado."""

from dataclasses import dataclass

from orchestrator.models import BankEntry, Divergence, LedgerEntry, MatchResult


@dataclass(frozen=True)
class WorkSet:
    bank: list[BankEntry]
    ledger: list[LedgerEntry]

    def as_divergences(self) -> list[Divergence]:
        """Uma divergência por lançamento órfão, banco primeiro.

        Esta derivação morava dentro de `reconcile`. Ela vem para cá inteira,
        sem mudança de ordem nem de formato de id, porque o agente recebe
        exatamente esta lista e o golden da Task 1 a pina indiretamente.
        """
        return [
            Divergence(
                id=f"d-b-{e.id}", bank_ids=frozenset({e.id}), ledger_ids=frozenset()
            )
            for e in self.bank
        ] + [
            Divergence(
                id=f"d-l-{e.id}", bank_ids=frozenset(), ledger_ids=frozenset({e.id})
            )
            for e in self.ledger
        ]

    def without(self, matches: list[MatchResult]) -> "WorkSet":
        """O pool sem o que estes vínculos resolveram.

        Recebe `list[MatchResult]`, não `ResolverOutput`, de propósito: assim
        não existe assinatura pela qual uma proposta possa chegar aqui. A
        invariante "proposta não resolve" deixa de ser regra que alguém lembra
        e passa a ser coisa que o tipo não sabe expressar.
        """
        if not matches:
            return WorkSet(bank=list(self.bank), ledger=list(self.ledger))
        casados_banco = {i for m in matches for i in m.bank_ids}
        casados_contabil = {i for m in matches for i in m.ledger_ids}
        return WorkSet(
            bank=[e for e in self.bank if e.id not in casados_banco],
            ledger=[e for e in self.ledger if e.id not in casados_contabil],
        )
