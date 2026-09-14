from datetime import date

import pytest

from orchestrator.dates import add_business_days, business_days_between


def test_dias_uteis_mesma_data():
    assert business_days_between(date(2026, 9, 14), date(2026, 9, 14)) == 0


def test_dias_uteis_dentro_da_semana():
    # segunda 14 -> quarta 16
    assert business_days_between(date(2026, 9, 14), date(2026, 9, 16)) == 2


def test_dias_uteis_atravessando_fim_de_semana():
    # sexta 18 -> segunda 21: um dia útil
    assert business_days_between(date(2026, 9, 18), date(2026, 9, 21)) == 1


def test_dias_uteis_e_simetrico():
    a, b = date(2026, 9, 18), date(2026, 9, 21)
    assert business_days_between(a, b) == business_days_between(b, a)


def test_add_business_days_pula_fim_de_semana():
    # sexta 18 + 1 dia útil = segunda 21
    assert add_business_days(date(2026, 9, 18), 1) == date(2026, 9, 21)


def test_add_business_days_zero():
    assert add_business_days(date(2026, 9, 14), 0) == date(2026, 9, 14)


def test_add_business_days_negativo_levanta_erro():
    with pytest.raises(ValueError):
        add_business_days(date(2026, 9, 14), -1)
