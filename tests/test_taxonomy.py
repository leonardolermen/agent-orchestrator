from orchestrator.domains.reconciliation.taxonomy import DivergenceType


def test_tipos_confirmados_existem():
    assert DivergenceType.RETENCAO_IMPOSTO
    assert DivergenceType.DEVOLUCAO_FUNDOS
    assert DivergenceType.PAGAMENTO_AGREGADO
    assert DivergenceType.DEFASAGEM_TEMPORAL
    assert DivergenceType.NAO_IDENTIFICADO


def test_valor_e_igual_ao_nome():
    # Serialização estável: o valor gravado é o nome do membro.
    for tipo in DivergenceType:
        assert tipo.value == tipo.name


def test_taxonomia_tem_quatorze_tipos():
    assert len(DivergenceType) == 14


def test_nao_identificado_e_o_fallback():
    assert DivergenceType("NAO_IDENTIFICADO") is DivergenceType.NAO_IDENTIFICADO
