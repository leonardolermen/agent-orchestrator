import pytest

from orchestrator.money import format_brl, parse_brl


def test_parse_brl_com_separador_de_milhar():
    assert parse_brl("R$ 1.234,56") == 123456


def test_parse_brl_sem_simbolo():
    assert parse_brl("1234,56") == 123456


def test_parse_brl_valor_negativo():
    assert parse_brl("-R$ 10,00") == -1000


def test_parse_brl_sem_centavos():
    assert parse_brl("R$ 50") == 5000


def test_parse_brl_rejeita_lixo():
    with pytest.raises(ValueError):
        parse_brl("abc")


def test_parse_brl_rejeita_centavos_com_tres_digitos():
    with pytest.raises(ValueError):
        parse_brl("10,999")


def test_parse_brl_rejeita_separador_decimal_sem_digitos():
    with pytest.raises(ValueError):
        parse_brl("10,")


def test_parse_brl_completa_centavos_com_um_digito():
    assert parse_brl("10,5") == 1050


def test_format_brl_positivo():
    assert format_brl(123456) == "R$ 1.234,56"


def test_format_brl_negativo():
    assert format_brl(-1000) == "-R$ 10,00"


def test_roundtrip():
    assert parse_brl(format_brl(987654)) == 987654
