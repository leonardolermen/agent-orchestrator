from random import Random

import pytest

from orchestrator.dates import business_days_between
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.synth.injectors import (
    DefasagemTemporal,
    DevolucaoFundos,
    PagamentoAgregado,
    RetencaoImposto,
    calcular_retencao,
)
from orchestrator.taxonomy import DivergenceType


def _par():
    return generate_clean_pairs(seed=1, n=1)[0]


def test_defasagem_muda_a_data_bancaria():
    par = _par()
    r = DefasagemTemporal().apply(Random(0), par)
    assert r.bank[0].date != par.bank.date


def test_defasagem_preserva_o_valor():
    par = _par()
    r = DefasagemTemporal().apply(Random(0), par)
    assert r.bank[0].amount == par.bank.amount


def test_defasagem_registra_o_gabarito():
    par = _par()
    r = DefasagemTemporal().apply(Random(0), par)
    assert r.truth.divergence_type is DivergenceType.DEFASAGEM_TEMPORAL
    assert r.truth.bank_ids == frozenset({par.bank.id})
    assert r.truth.ledger_ids == frozenset({par.ledger.id})


def test_defasagem_e_deterministica():
    par = _par()
    a = DefasagemTemporal().apply(Random(99), par)
    b = DefasagemTemporal().apply(Random(99), par)
    assert a.bank[0].date == b.bank[0].date


def test_defasagem_excede_a_tolerancia_da_camada_l2():
    # A tolerância padrão de L2 é 3 dias úteis; a injeção precisa passar disso
    # para que o caso de fato vire divergência.
    par = _par()
    r = DefasagemTemporal().apply(Random(0), par)
    assert business_days_between(r.bank[0].date, par.ledger.cash_date) > 3


def test_calcular_retencao_iss_cinco_por_cento():
    # 500 basis points = 5%
    assert calcular_retencao(100_000, 500) == 5_000


def test_calcular_retencao_arredonda_para_baixo():
    assert calcular_retencao(333, 500) == 16  # 16,65 centavos -> 16


def test_retencao_reduz_o_valor_bancario():
    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    assert abs(r.bank[0].amount) < par.ledger.gross_amount


def test_retencao_nao_toca_o_lancamento_contabil():
    # A empresa lança pelo bruto, o banco paga o líquido, e a diferença é a
    # divergência. Se a contabilidade já registrasse o líquido, os dois lados
    # bateriam e não haveria divergência nenhuma.
    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    assert r.ledger[0] == par.ledger


def test_retencao_sobra_para_o_agente():
    # A guarda que faltava. Sem ela, o injetor produzia um caso que L1 casava
    # em cheio enquanto o gabarito afirmava divergência — dois falsos positivos
    # medidos em benchmark antes de alguém notar.
    from orchestrator.matching.exact import ExactMatcher
    from orchestrator.matching.tolerance import ToleranceMatcher
    from orchestrator.workflow.workset import WorkSet

    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    work = WorkSet(bank=r.bank, ledger=r.ledger)

    assert ExactMatcher().resolve(work).matches == []
    assert ToleranceMatcher().resolve(work).matches == []


def test_retencao_e_deterministica():
    # Determinismo por semente é um Global Constraint do projeto: a mesma
    # semente precisa produzir o mesmo resultado, também para este injetor.
    par = _par()
    a = RetencaoImposto().apply(Random(42), par)
    b = RetencaoImposto().apply(Random(42), par)
    assert a.bank[0].amount == b.bank[0].amount
    assert a.truth.explanation == b.truth.explanation


def test_retencao_registra_o_gabarito():
    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    assert r.truth.divergence_type is DivergenceType.RETENCAO_IMPOSTO


def _pares(n: int):
    return generate_clean_pairs(seed=11, n=n)


def test_agregado_produz_um_lancamento_bancario():
    pares = _pares(3)
    r = PagamentoAgregado().apply_many(Random(0), pares)
    assert len(r.bank) == 1


def test_agregado_preserva_todos_os_contabeis():
    pares = _pares(3)
    r = PagamentoAgregado().apply_many(Random(0), pares)
    assert len(r.ledger) == 3


def test_agregado_soma_os_liquidos():
    pares = _pares(4)
    r = PagamentoAgregado().apply_many(Random(0), pares)
    esperado = sum(p.ledger.net_amount for p in pares)
    assert abs(r.bank[0].amount) == esperado


def test_agregado_registra_todos_os_ids_no_gabarito():
    pares = _pares(3)
    r = PagamentoAgregado().apply_many(Random(0), pares)
    assert r.truth.ledger_ids == frozenset(p.ledger.id for p in pares)
    assert len(r.truth.bank_ids) == 1


def test_agregado_declara_todos_os_pares_consumidos():
    # Guarda de regressão do defeito mais caro deste plano: declarar só o
    # primeiro par deixaria os outros originais órfãos no dataset, somando
    # dinheiro que não existe. Sem esta asserção, a reversão passa despercebida.
    pares = _pares(3)
    r = PagamentoAgregado().apply_many(Random(0), pares)
    assert r.consumed == tuple(pares)


def test_agregado_exige_pelo_menos_dois_pares():
    with pytest.raises(ValueError):
        PagamentoAgregado().apply_many(Random(0), _pares(1))


def test_agregado_e_esperado_no_deterministico():
    # L3 deve resolver: o gabarito precisa dizer isso, senão a métrica conta
    # como falso positivo quando o sistema acerta.
    r = PagamentoAgregado().apply_many(Random(0), _pares(3))
    assert r.truth.deterministic_expected is True


def test_defasagem_e_retencao_nao_sao_deterministicos():
    par = _par()
    assert DefasagemTemporal().apply(Random(0), par).truth.deterministic_expected is False
    assert RetencaoImposto().apply(Random(0), par).truth.deterministic_expected is False


def test_agregado_normaliza_fornecedor_e_data():
    # Sem isto, a camada L3 (que agrupa por fornecedor dentro de uma janela de
    # dias úteis) nunca encontraria o conjunto.
    r = PagamentoAgregado().apply_many(Random(0), _pares(3))
    assert len({le.supplier for le in r.ledger}) == 1
    assert all(le.cash_date == r.bank[0].date for le in r.ledger)


def test_devolucao_produz_tres_pernas_bancarias():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    assert len(r.bank) == 3


def test_devolucao_soma_das_pernas_iguala_o_debito_original():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    # débito, estorno de volta, e reenvio: o efeito líquido é um débito só
    assert sum(e.amount for e in r.bank) == par.bank.amount


def test_devolucao_tem_uma_perna_de_credito():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    creditos = [e for e in r.bank if e.amount > 0]
    assert len(creditos) == 1


def test_devolucao_pernas_tem_ids_distintos():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    assert len({e.id for e in r.bank}) == 3


def test_devolucao_em_ordem_cronologica():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    datas = [e.date for e in r.bank]
    assert datas == sorted(datas)


def test_devolucao_gabarito_cobre_todas_as_pernas():
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    assert r.truth.bank_ids == frozenset(e.id for e in r.bank)
    assert r.truth.divergence_type is DivergenceType.DEVOLUCAO_FUNDOS
    assert r.consumed == (par,)


def test_devolucao_e_deterministica():
    # DevolucaoFundos consome dois draws de randrange (devolução e reenvio).
    # Determinismo por semente é um Global Constraint: a mesma semente precisa
    # reproduzir exatamente as mesmas três datas.
    par = _par()
    a = DevolucaoFundos().apply(Random(42), par)
    b = DevolucaoFundos().apply(Random(42), par)
    assert [e.date for e in a.bank] == [e.date for e in b.bank]


def test_devolucao_zera_o_documento_das_pernas():
    # L1 e L2 exigem documento não nulo. Sem zerar, L1 casaria a perna de envio
    # com o lançamento contábil e o caso viraria falso positivo.
    par = _par()
    r = DevolucaoFundos().apply(Random(0), par)
    assert all(e.document is None for e in r.bank)
