from dataclasses import replace

from orchestrator.dates import add_business_days
from orchestrator.matching.tolerance import ToleranceMatcher
from orchestrator.synth.generator import generate_clean_pairs


def _par():
    return generate_clean_pairs(seed=4, n=1)[0]


def test_casa_com_diferenca_de_centavos_dentro_da_tolerancia():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 3)]

    r = ToleranceMatcher().match(banco, [par.ledger])

    assert len(r) == 1
    assert r[0].layer == "L2"


def test_nao_casa_com_diferenca_acima_da_tolerancia_de_valor():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 500)]

    assert ToleranceMatcher().match(banco, [par.ledger]) == []


def test_casa_com_atraso_dentro_da_tolerancia_de_dias():
    par = _par()
    banco = [replace(par.bank, date=add_business_days(par.bank.date, 2))]

    assert len(ToleranceMatcher().match(banco, [par.ledger])) == 1


def test_nao_casa_com_atraso_acima_da_tolerancia_de_dias():
    par = _par()
    banco = [replace(par.bank, date=add_business_days(par.bank.date, 8))]

    assert ToleranceMatcher().match(banco, [par.ledger]) == []


def test_tolerancia_e_configuravel():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 50)]

    assert ToleranceMatcher(max_cents=100).match(banco, [par.ledger]) != []
    assert ToleranceMatcher(max_cents=10).match(banco, [par.ledger]) == []


def test_registra_a_diferenca_na_evidencia():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 3)]

    r = ToleranceMatcher().match(banco, [par.ledger])[0]

    assert r.evidence["diferenca_centavos"] == 3


def test_rejeita_tolerancia_negativa():
    # Tolerância negativa não casaria nada e pareceria só uma camada sem achados.
    import pytest

    with pytest.raises(ValueError):
        ToleranceMatcher(max_cents=-1)
    with pytest.raises(ValueError):
        ToleranceMatcher(max_business_days=-1)
