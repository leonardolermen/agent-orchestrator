"""Contrato comum das camadas de matching."""

from typing import Protocol

from orchestrator.models import BankEntry, LedgerEntry, MatchResult


class Matcher(Protocol):
    """Uma camada determinística.

    Recebe apenas o que ainda não foi casado e devolve os vínculos que
    conseguiu estabelecer, cada um com a regra que o justificou.
    """

    layer: str

    def match(self, bank: list[BankEntry], ledger: list[LedgerEntry]) -> list[MatchResult]: ...
