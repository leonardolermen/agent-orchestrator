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


# Alíquotas em basis points (1% = 100 bp). Valores típicos de retenção na fonte.
_ALIQUOTAS = {
    "ISS": 500,      # 5%
    "IRRF": 150,     # 1,5%
    "CSLL/PIS/COFINS": 465,  # 4,65%
    "INSS": 1100,    # 11%
}


def calcular_retencao(bruto: int, aliquota_bp: int) -> int:
    """Retenção em centavos, truncada para baixo.

    Determinística e testável de propósito: cálculo fiscal não pode depender
    de raciocínio de modelo de linguagem. Ver spec 4.6.
    """
    return bruto * aliquota_bp // 10_000


class RetencaoImposto:
    """O banco credita o líquido; a contabilidade registra o bruto."""

    divergence_type = DivergenceType.RETENCAO_IMPOSTO

    def apply(self, rng: Random, pair: Pair) -> InjectionResult:
        nome, aliquota = rng.choice(sorted(_ALIQUOTAS.items()))
        bruto = pair.ledger.gross_amount
        retido = calcular_retencao(bruto, aliquota)
        liquido = bruto - retido

        banco = replace(pair.bank, amount=-liquido)
        contabil = replace(pair.ledger, net_amount=liquido)

        return InjectionResult(
            consumed=(pair,),
            bank=[banco],
            ledger=[contabil],
            truth=GroundTruth(
                divergence_type=self.divergence_type,
                bank_ids=frozenset({banco.id}),
                ledger_ids=frozenset({contabil.id}),
                explanation=(
                    f"{nome} retido na fonte a {aliquota / 100:.2f}%: bruto de "
                    f"{bruto} centavos, retenção de {retido}, líquido de {liquido}."
                ),
            ),
        )


class PagamentoAgregado:
    """Um único débito bancário cobre N documentos contábeis.

    Diferente dos demais injetores: consome vários pares, porque a divergência
    só existe entre múltiplas notas. Por isso expõe apply_many, não apply.
    """

    divergence_type = DivergenceType.PAGAMENTO_AGREGADO

    def apply_many(self, rng: Random, pairs: list[Pair]) -> InjectionResult:
        if len(pairs) < 2:
            raise ValueError("pagamento agregado exige pelo menos dois pares")

        total = sum(p.ledger.net_amount for p in pairs)
        primeiro = pairs[0]
        documentos = ", ".join(sorted(p.ledger.document or p.ledger.id for p in pairs))

        banco = replace(
            primeiro.bank,
            amount=-total,
            description=f"PAGTO LOTE {len(pairs)} DOCS",
            document=None,
        )

        # Um pagamento em lote é a um único fornecedor e liquida tudo no mesmo
        # dia. Sem normalizar as duas coisas, a camada L3 — que agrupa por
        # fornecedor dentro de uma janela de dias úteis — nunca encontraria o
        # conjunto, e o caso que ela existe para resolver viraria divergência.
        contabeis = [
            replace(p.ledger, supplier=primeiro.ledger.supplier, cash_date=banco.date)
            for p in pairs
        ]

        return InjectionResult(
            consumed=tuple(pairs),
            bank=[banco],
            ledger=contabeis,
            truth=GroundTruth(
                divergence_type=self.divergence_type,
                bank_ids=frozenset({banco.id}),
                ledger_ids=frozenset(le.id for le in contabeis),
                explanation=(
                    f"Um débito de {total} centavos cobre {len(pairs)} documentos: "
                    f"{documentos}."
                ),
                # A camada L3 deve resolver este caso sozinha.
                deterministic_expected=True,
            ),
        )
