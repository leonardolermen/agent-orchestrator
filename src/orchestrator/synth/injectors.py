"""Injetores de divergência.

Um injetor por tipo da taxonomia. Adicionar um tipo novo custa uma classe
aqui e uma entrada na enum — nada estrutural. Ver spec 4.5.
"""

from dataclasses import replace
from random import Random
from typing import Protocol

from orchestrator.dates import add_business_days
from orchestrator.synth.dataset import GroundTruth, InjectionResult, Pair
from orchestrator.tax import _ALIQUOTAS, calcular_retencao
from orchestrator.taxonomy import DivergenceType

__all__ = [
    "DefasagemTemporal",
    "DevolucaoFundos",
    "Injector",
    "PagamentoAgregado",
    "RetencaoImposto",
    "calcular_retencao",
]


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


class RetencaoImposto:
    """O banco credita o líquido; a contabilidade registra o bruto."""

    divergence_type = DivergenceType.RETENCAO_IMPOSTO

    def apply(self, rng: Random, pair: Pair) -> InjectionResult:
        nome, aliquota = rng.choice(sorted(_ALIQUOTAS.items()))
        bruto = pair.ledger.gross_amount
        retido = calcular_retencao(bruto, aliquota)
        liquido = bruto - retido

        # O lançamento contábil NÃO é tocado. A empresa registra a nota pelo
        # bruto; o banco paga o líquido; e a diferença entre os dois é
        # exatamente o que o reconciliador enxerga e o agente precisa explicar.
        # Reescrever o líquido do contábil faria os dois lados baterem, a
        # camada L1 casaria o caso em cheio, e o gabarito passaria a afirmar
        # uma divergência que não existe.
        banco = replace(pair.bank, amount=-liquido)

        return InjectionResult(
            consumed=(pair,),
            bank=[banco],
            ledger=[pair.ledger],
            truth=GroundTruth(
                divergence_type=self.divergence_type,
                bank_ids=frozenset({banco.id}),
                ledger_ids=frozenset({pair.ledger.id}),
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
        # rng não é usado aqui — a fusão em um único débito é determinística
        # dado o conjunto de pares. O parâmetro fica por simetria com o
        # protocolo Injector (e com apply_many como contraparte de apply):
        # quem chama não precisa saber qual injetor usa aleatoriedade e qual
        # não usa.
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


class DevolucaoFundos:
    """TED ou Pix devolvido, com reenvio posterior.

    Produz três pernas bancárias para um único lançamento contábil:
    o débito original, o crédito de devolução, e o reenvio corrigido.
    Nenhuma camada determinística resolve isso — é o caso que vai para o
    agente de investigação.
    """

    divergence_type = DivergenceType.DEVOLUCAO_FUNDOS

    def apply(self, rng: Random, pair: Pair) -> InjectionResult:
        valor = pair.bank.amount  # negativo
        data_envio = pair.bank.date
        data_devolucao = add_business_days(data_envio, rng.randrange(1, 3))
        data_reenvio = add_business_days(data_devolucao, rng.randrange(1, 5))

        # As três pernas perdem a referência do documento. Isso espelha o
        # extrato real — transferência devolvida aparece como movimentação
        # genérica — e tem uma consequência de desenho: L1 e L2 exigem
        # documento não nulo, então nenhuma das duas casa estas pernas. Sem
        # isso, L1 casaria a perna de envio com o lançamento contábil (mesmo
        # documento, valor e data do original) e o caso que o spec reserva
        # para o agente viraria falso positivo.
        envio = replace(pair.bank, id=f"{pair.bank.id}-a", date=data_envio, document=None)
        devolucao = replace(
            pair.bank,
            id=f"{pair.bank.id}-b",
            date=data_devolucao,
            amount=-valor,
            description="DEVOLUCAO TED",
            document=None,
        )
        reenvio = replace(
            pair.bank,
            id=f"{pair.bank.id}-c",
            date=data_reenvio,
            amount=valor,
            description=f"{pair.bank.description} REENVIO",
            document=None,
        )

        return InjectionResult(
            consumed=(pair,),
            bank=[envio, devolucao, reenvio],
            ledger=[pair.ledger],
            truth=GroundTruth(
                divergence_type=self.divergence_type,
                bank_ids=frozenset({envio.id, devolucao.id, reenvio.id}),
                ledger_ids=frozenset({pair.ledger.id}),
                explanation=(
                    f"Pagamento enviado em {data_envio}, devolvido em "
                    f"{data_devolucao} e reenviado em {data_reenvio}. Três "
                    f"lançamentos bancários para um documento."
                ),
            ),
        )
