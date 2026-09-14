from random import Random

from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.synth.injectors import DevolucaoFundos, PagamentoAgregado


def test_casa_pagamento_agregado_de_tres_notas():
    pares = generate_clean_pairs(seed=6, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    r = GroupingMatcher().match(inj.bank, inj.ledger)

    assert len(r) == 1
    assert r[0].ledger_ids == frozenset(le.id for le in inj.ledger)
    assert r[0].layer == "L3"


def test_nao_casa_grupo_maior_que_o_limite():
    pares = generate_clean_pairs(seed=6, n=6)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    assert GroupingMatcher(max_group_size=4).match(inj.bank, inj.ledger) == []


def test_nao_resolve_devolucao_de_fundos():
    # Devolução é caso do agente, não das camadas determinísticas. Ver spec 4.5.
    par = generate_clean_pairs(seed=6, n=1)[0]
    inj = DevolucaoFundos().apply(Random(0), par)

    assert GroupingMatcher().match(inj.bank, inj.ledger) == []


def test_registra_as_parcelas_na_evidencia():
    pares = generate_clean_pairs(seed=6, n=2)
    inj = PagamentoAgregado().apply_many(Random(0), pares)

    r = GroupingMatcher().match(inj.bank, inj.ledger)[0]

    assert r.evidence["quantidade"] == 2
    assert r.evidence["soma"] == abs(inj.bank[0].amount)


def test_nao_agrupa_fornecedores_diferentes():
    from dataclasses import replace

    pares = generate_clean_pairs(seed=6, n=2)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    contabeis = [inj.ledger[0], replace(inj.ledger[1], supplier="OUTRO FORNECEDOR SA")]

    assert GroupingMatcher().match(inj.bank, contabeis) == []


def test_rejeita_configuracao_que_nunca_agrupa():
    # Tamanho 1 esvazia o range de combinações: a camada nunca agruparia nada,
    # sem erro e sem aviso.
    import pytest

    with pytest.raises(ValueError):
        GroupingMatcher(max_group_size=1)
    with pytest.raises(ValueError):
        GroupingMatcher(max_business_days=-1)
