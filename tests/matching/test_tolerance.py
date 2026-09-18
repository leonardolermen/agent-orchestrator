from dataclasses import replace

from orchestrator.domains.reconciliation.dates import add_business_days
from orchestrator.domains.reconciliation.models import pool
from orchestrator.domains.reconciliation.resolvers.tolerance import ToleranceMatcher
from orchestrator.domains.reconciliation.synth.generator import generate_clean_pairs


def _par():
    return generate_clean_pairs(seed=4, n=1)[0]


def test_casa_com_diferenca_de_centavos_dentro_da_tolerancia():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 3)]

    r = ToleranceMatcher().resolve(pool(bank=banco, ledger=[par.ledger])).resolutions

    assert len(r) == 1
    assert r[0].produced_by == "L2"


def test_nao_casa_com_diferenca_acima_da_tolerancia_de_valor():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 500)]

    assert ToleranceMatcher().resolve(pool(bank=banco, ledger=[par.ledger])).resolutions == []


def test_casa_com_atraso_dentro_da_tolerancia_de_dias():
    par = _par()
    banco = [replace(par.bank, date=add_business_days(par.bank.date, 2))]

    assert (
        len(ToleranceMatcher().resolve(pool(bank=banco, ledger=[par.ledger])).resolutions)
        == 1
    )


def test_nao_casa_com_atraso_acima_da_tolerancia_de_dias():
    par = _par()
    banco = [replace(par.bank, date=add_business_days(par.bank.date, 8))]

    assert ToleranceMatcher().resolve(pool(bank=banco, ledger=[par.ledger])).resolutions == []


def test_tolerancia_e_configuravel():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 50)]

    assert (
        ToleranceMatcher(max_cents=100).resolve(pool(bank=banco, ledger=[par.ledger])).resolutions
        != []
    )
    assert (
        ToleranceMatcher(max_cents=10).resolve(pool(bank=banco, ledger=[par.ledger])).resolutions
        == []
    )


def test_registra_a_diferenca_na_evidencia():
    par = _par()
    banco = [replace(par.bank, amount=par.bank.amount + 3)]

    r = ToleranceMatcher().resolve(pool(bank=banco, ledger=[par.ledger])).resolutions[0]

    assert r.evidence["diferenca_centavos"] == 3


def test_fronteira_de_valor_e_inclusiva():
    # A fronteira precisa estar fixada: a taxa de resolução determinística
    # desloca silenciosamente se a inclusividade mudar, e ela é o número que
    # este projeto existe para medir.
    par = _par()
    no_limite = [replace(par.bank, amount=par.bank.amount + 5)]
    um_alem = [replace(par.bank, amount=par.bank.amount + 6)]

    assert (
        len(
            ToleranceMatcher().resolve(pool(bank=no_limite, ledger=[par.ledger])).resolutions
        )
        == 1
    )
    assert (
        ToleranceMatcher().resolve(pool(bank=um_alem, ledger=[par.ledger])).resolutions == []
    )


def test_fronteira_de_dias_e_inclusiva():
    par = _par()
    no_limite = [replace(par.bank, date=add_business_days(par.bank.date, 3))]
    um_alem = [replace(par.bank, date=add_business_days(par.bank.date, 4))]

    assert (
        len(
            ToleranceMatcher().resolve(pool(bank=no_limite, ledger=[par.ledger])).resolutions
        )
        == 1
    )
    assert (
        ToleranceMatcher().resolve(pool(bank=um_alem, ledger=[par.ledger])).resolutions == []
    )


def test_cada_lancamento_e_usado_uma_vez_so():
    # Duas entradas bancárias disputando o mesmo lançamento contábil: só uma
    # pode consumi-lo. Sem esta guarda, a mesma nota conciliaria duas vezes e
    # a taxa de resolução determinística infla por dupla contagem — o mesmo
    # invariante que L1 já guarda, e que faltava aqui.
    par = _par()
    concorrente = replace(par.bank, id="b-concorrente", amount=par.bank.amount + 2)
    banco = [par.bank, concorrente]

    resultados = ToleranceMatcher().resolve(pool(bank=banco, ledger=[par.ledger])).resolutions

    assert len(resultados) == 1


def test_rejeita_tolerancia_negativa():
    # Tolerância negativa não casaria nada e pareceria só uma camada sem achados.
    import pytest

    with pytest.raises(ValueError):
        ToleranceMatcher(max_cents=-1)
    with pytest.raises(ValueError):
        ToleranceMatcher(max_business_days=-1)
