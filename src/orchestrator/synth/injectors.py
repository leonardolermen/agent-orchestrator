"""Injetores de divergência.

Um injetor por tipo da taxonomia. Adicionar um tipo novo custa uma classe
aqui e uma entrada na enum — nada estrutural. Ver spec 4.5.
"""

from dataclasses import replace
from random import Random
from typing import Protocol

from orchestrator.dates import add_business_days
from orchestrator.synth.dataset import GroundTruth, InjectionResult, Pair
from orchestrator.taxonomy import DivergenceType


class Injector(Protocol):
    """Reescreve um par limpo, introduzindo uma divergência conhecida."""

    divergence_type: DivergenceType

    def apply(self, rng: Random, pair: Pair) -> InjectionResult: ...


class DefasagemTemporal:
    """A liquidação bancária cai bem depois da data prevista em caixa."""

    divergence_type = DivergenceType.DEFASAGEM_TEMPORAL

    def apply(self, rng: Random, pair: Pair) -> InjectionResult:
        atraso = rng.randrange(4, 12)  # sempre acima da tolerância de L2
        nova_data = add_business_days(pair.bank.date, atraso)
        banco = replace(pair.bank, date=nova_data)

        return InjectionResult(
            consumed=(pair,),
            bank=[banco],
            ledger=[pair.ledger],
            truth=GroundTruth(
                divergence_type=self.divergence_type,
                bank_ids=frozenset({banco.id}),
                ledger_ids=frozenset({pair.ledger.id}),
                explanation=(
                    f"Liquidação ocorreu {atraso} dias úteis após a data prevista "
                    f"em caixa ({pair.ledger.cash_date})."
                ),
            ),
        )
