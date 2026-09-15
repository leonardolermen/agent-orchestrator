from random import Random

from orchestrator.matching.exact import ExactMatcher
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal
from orchestrator.workflow.workset import WorkSet


def test_casa_todos_os_pares_limpos():
    pares = generate_clean_pairs(seed=2, n=25)
    banco = [p.bank for p in pares]
    contabil = [p.ledger for p in pares]

    resultados = ExactMatcher().resolve(WorkSet(bank=banco, ledger=contabil)).matches

    assert len(resultados) == 25
    assert all(r.layer == "L1" for r in resultados)


def test_nao_casa_quando_a_data_diverge():
    par = generate_clean_pairs(seed=2, n=1)[0]
    injetado = DefasagemTemporal().apply(Random(0), par)

    resultados = (
        ExactMatcher()
        .resolve(WorkSet(bank=injetado.bank, ledger=injetado.ledger))
        .matches
    )

    assert resultados == []


def test_nao_casa_quando_o_valor_diverge():
    from dataclasses import replace

    par = generate_clean_pairs(seed=2, n=1)[0]
    banco = [replace(par.bank, amount=par.bank.amount - 1)]

    resultados = ExactMatcher().resolve(WorkSet(bank=banco, ledger=[par.ledger])).matches

    assert resultados == []


def test_resultado_registra_a_regra():
    pares = generate_clean_pairs(seed=2, n=1)
    r = (
        ExactMatcher()
        .resolve(WorkSet(bank=[pares[0].bank], ledger=[pares[0].ledger]))
        .matches[0]
    )
    assert "exato" in r.rule.lower()
    assert r.evidence["documento"] == pares[0].ledger.document


def test_cada_lancamento_e_usado_uma_vez_so():
    from dataclasses import replace

    par = generate_clean_pairs(seed=2, n=1)[0]
    # dois contábeis idênticos disputando um único bancário
    gemeo = replace(par.ledger, id="l-gemeo")

    resultados = (
        ExactMatcher()
        .resolve(WorkSet(bank=[par.bank], ledger=[par.ledger, gemeo]))
        .matches
    )

    assert len(resultados) == 1
