from random import Random

from orchestrator.matching.exact import ExactMatcher
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal


def test_casa_todos_os_pares_limpos():
    pares = generate_clean_pairs(seed=2, n=25)
    banco = [p.bank for p in pares]
    contabil = [p.ledger for p in pares]

    resultados = ExactMatcher().match(banco, contabil)

    assert len(resultados) == 25
    assert all(r.layer == "L1" for r in resultados)


def test_nao_casa_quando_a_data_diverge():
    par = generate_clean_pairs(seed=2, n=1)[0]
    injetado = DefasagemTemporal().apply(Random(0), par)

    resultados = ExactMatcher().match(injetado.bank, injetado.ledger)

    assert resultados == []


def test_nao_casa_quando_o_valor_diverge():
    from dataclasses import replace

    par = generate_clean_pairs(seed=2, n=1)[0]
    banco = [replace(par.bank, amount=par.bank.amount - 1)]

    resultados = ExactMatcher().match(banco, [par.ledger])

    assert resultados == []


def test_resultado_registra_a_regra():
    pares = generate_clean_pairs(seed=2, n=1)
    r = ExactMatcher().match([pares[0].bank], [pares[0].ledger])[0]
    assert "exato" in r.rule.lower()
    assert r.evidence["documento"] == pares[0].ledger.document


def test_cada_lancamento_e_usado_uma_vez_so():
    from dataclasses import replace

    par = generate_clean_pairs(seed=2, n=1)[0]
    # dois contábeis idênticos disputando um único bancário
    gemeo = replace(par.ledger, id="l-gemeo")

    resultados = ExactMatcher().match([par.bank], [par.ledger, gemeo])

    assert len(resultados) == 1
