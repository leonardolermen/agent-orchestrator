from datetime import date

import pytest

from orchestrator.models import BankEntry, Divergence, LedgerEntry, MatchResult


def _bank(id_: str = "b1", amount: int = -10000) -> BankEntry:
    return BankEntry(
        id=id_,
        date=date(2026, 9, 14),
        amount=amount,
        description="PAGTO FORNECEDOR",
        counterparty="ACME LTDA",
        document="NF-1001",
    )


def _ledger(id_: str = "l1", net: int = 10000) -> LedgerEntry:
    return LedgerEntry(
        id=id_,
        accrual_date=date(2026, 9, 10),
        cash_date=date(2026, 9, 14),
        gross_amount=net,
        net_amount=net,
        account="2.1.1.01",
        cost_center="ADM",
        document="NF-1001",
        supplier="ACME LTDA",
    )


def test_entradas_sao_imutaveis():
    b = _bank()
    with pytest.raises(AttributeError):
        b.amount = 1  # type: ignore[misc]


def test_match_result_guarda_conjuntos():
    m = MatchResult(
        bank_ids=frozenset({"b1"}),
        ledger_ids=frozenset({"l1", "l2"}),
        layer="L3",
        rule="soma de líquidos igual ao crédito",
        evidence={"soma": 10000},
    )
    assert m.ledger_ids == frozenset({"l1", "l2"})
    assert m.layer == "L3"


def test_match_result_rejeita_lado_vazio():
    with pytest.raises(ValueError):
        MatchResult(
            bank_ids=frozenset(),
            ledger_ids=frozenset({"l1"}),
            layer="L1",
            rule="",
            evidence={},
        )


def test_divergence_aceita_lado_vazio():
    # Um lançamento contábil sem contrapartida bancária é divergência válida.
    d = Divergence(id="d1", bank_ids=frozenset(), ledger_ids=frozenset({"l1"}))
    assert d.ledger_ids == frozenset({"l1"})


def test_divergence_rejeita_ambos_vazios():
    with pytest.raises(ValueError):
        Divergence(id="d1", bank_ids=frozenset(), ledger_ids=frozenset())


def test_bank_entry_negativo_e_debito():
    assert _bank(amount=-10000).amount < 0
