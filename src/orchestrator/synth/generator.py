"""Geração de datasets sintéticos determinísticos.

Primeiro cria pares que conciliam perfeitamente; depois injetores reescrevem
uma fração deles. Determinismo por semente é requisito: a mesma semente
produz exatamente o mesmo dataset.
"""

from datetime import date, timedelta
from random import Random

from orchestrator.dates import add_business_days
from orchestrator.models import BankEntry, LedgerEntry
from orchestrator.synth.dataset import Dataset, InjectionResult, Pair

_FORNECEDORES = [
    "ACME SERVICOS LTDA",
    "BETA DISTRIBUIDORA SA",
    "GAMA TECNOLOGIA ME",
    "DELTA LOGISTICA LTDA",
    "EPSILON CONSULTORIA SS",
    "ZETA MANUTENCAO EIRELI",
]

_CONTAS = ["2.1.1.01", "2.1.1.02", "4.1.2.03", "4.1.5.01"]
_CENTROS = ["ADM", "COM", "OPE", "TI"]
_BASE = date(2026, 6, 1)


def generate_clean_pairs(seed: int, n: int) -> list[Pair]:
    """Gera n pares que conciliam perfeitamente."""
    # Um n inválido devolveria lista vazia em silêncio, e toda métrica
    # calculada em cima dela sairia zerada sem nenhum sinal de que o dataset
    # nunca existiu.
    if n < 1:
        raise ValueError(f"n precisa ser pelo menos 1: {n}")

    rng = Random(seed)
    pares: list[Pair] = []

    for i in range(n):
        fornecedor = rng.choice(_FORNECEDORES)
        valor = rng.randrange(5_000, 5_000_000)  # R$ 50,00 a R$ 50.000,00
        competencia = _BASE + timedelta(days=rng.randrange(0, 90))
        caixa = add_business_days(competencia, rng.randrange(0, 5))
        documento = f"NF-{10_000 + i}"

        banco = BankEntry(
            id=f"b{i:05d}",
            date=caixa,
            amount=-valor,
            description=f"PAGTO {fornecedor[:20]}",
            counterparty=fornecedor,
            document=documento,
        )
        contabil = LedgerEntry(
            id=f"l{i:05d}",
            accrual_date=competencia,
            cash_date=caixa,
            gross_amount=valor,
            net_amount=valor,
            account=rng.choice(_CONTAS),
            supplier=fornecedor,
            cost_center=rng.choice(_CENTROS),
            document=documento,
        )
        pares.append(Pair(bank=banco, ledger=contabil))

    return pares


def build_dataset(pares: list[Pair], injections: list[InjectionResult]) -> Dataset:
    """Monta o dataset final.

    Os pares que cada injeção declara ter consumido saem do dataset, e os
    lançamentos que o injetor produziu entram no lugar.

    A substituição usa `inj.consumed`, nunca os ids da saída do injetor: a
    devolução de fundos renomeia as três pernas e o pagamento agregado funde
    N pares num lançamento só, então inferir por id deixaria originais órfãos
    somando dinheiro que não existe.
    """
    # Duas injeções declarando o mesmo par, ou uma injeção declarando um par
    # que não está em `pares`, silenciosamente duplicaria ou inventaria
    # entradas — a mesma classe de "dinheiro que não existe" que `consumed`
    # foi desenhado para prevenir (ver docstring de InjectionResult), um nível
    # acima onde nada mais checa isso.
    ids_pares_validos = {p.bank.id for p in pares}
    vistos: set[str] = set()
    for inj in injections:
        for p in inj.consumed:
            if p.bank.id not in ids_pares_validos:
                raise ValueError(
                    f"par consumido não pertence ao dataset base: {p.bank.id}"
                )
            if p.bank.id in vistos:
                raise ValueError(
                    f"par consumido por mais de uma injeção: {p.bank.id}"
                )
            vistos.add(p.bank.id)

    substituidos_banco = {p.bank.id for inj in injections for p in inj.consumed}
    substituidos_contabil = {p.ledger.id for inj in injections for p in inj.consumed}

    banco: list[BankEntry] = []
    contabil: list[LedgerEntry] = []

    for p in pares:
        if p.bank.id not in substituidos_banco:
            banco.append(p.bank)
        if p.ledger.id not in substituidos_contabil:
            contabil.append(p.ledger)

    for inj in injections:
        banco.extend(inj.bank)
        contabil.extend(inj.ledger)

    banco.sort(key=lambda e: (e.date, e.id))
    contabil.sort(key=lambda e: (e.accrual_date, e.id))

    return Dataset(bank=banco, ledger=contabil, truth=[inj.truth for inj in injections])
