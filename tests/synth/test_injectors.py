from random import Random

from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal
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
    from orchestrator.dates import business_days_between

    par = _par()
    r = DefasagemTemporal().apply(Random(0), par)
    assert business_days_between(r.bank[0].date, par.ledger.cash_date) > 3


from orchestrator.synth.injectors import RetencaoImposto, calcular_retencao


def test_calcular_retencao_iss_cinco_por_cento():
    # 500 basis points = 5%
    assert calcular_retencao(100_000, 500) == 5_000


def test_calcular_retencao_arredonda_para_baixo():
    assert calcular_retencao(333, 500) == 16  # 16,65 centavos -> 16


def test_retencao_reduz_o_valor_bancario():
    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    assert abs(r.bank[0].amount) < par.ledger.gross_amount


def test_retencao_mantem_bruto_e_ajusta_liquido():
    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    contabil = r.ledger[0]
    assert contabil.gross_amount == par.ledger.gross_amount
    assert contabil.net_amount == abs(r.bank[0].amount)
    assert contabil.net_amount < contabil.gross_amount


def test_retencao_registra_o_gabarito():
    par = _par()
    r = RetencaoImposto().apply(Random(0), par)
    assert r.truth.divergence_type is DivergenceType.RETENCAO_IMPOSTO
