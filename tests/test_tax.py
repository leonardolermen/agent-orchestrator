from orchestrator.tax import calcular_retencao


def test_calcular_retencao_iss_cinco_por_cento():
    # 500 basis points = 5%
    assert calcular_retencao(100_000, 500) == 5_000


def test_calcular_retencao_arredonda_para_baixo():
    assert calcular_retencao(333, 500) == 16  # 16,65 centavos -> 16


def test_calcular_retencao_e_inteiro():
    assert isinstance(calcular_retencao(333, 500), int)
