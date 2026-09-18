from random import Random

from orchestrator.domains.reconciliation.models import pool
from orchestrator.domains.reconciliation.resolvers.exact import ExactMatcher
from orchestrator.domains.reconciliation.synth.generator import generate_clean_pairs
from orchestrator.domains.reconciliation.synth.injectors import DefasagemTemporal


def test_casa_todos_os_pares_limpos():
    pares = generate_clean_pairs(seed=2, n=25)
    banco = [p.bank for p in pares]
    contabil = [p.ledger for p in pares]

    resultados = ExactMatcher().resolve(pool(bank=banco, ledger=contabil)).resolutions

    assert len(resultados) == 25
    assert all(r.produced_by == "L1" for r in resultados)


def test_nao_casa_quando_a_data_diverge():
    par = generate_clean_pairs(seed=2, n=1)[0]
    injetado = DefasagemTemporal().apply(Random(0), par)

    resultados = (
        ExactMatcher()
        .resolve(pool(bank=injetado.bank, ledger=injetado.ledger))
        .resolutions
    )

    assert resultados == []


def test_nao_casa_quando_o_valor_diverge():
    from dataclasses import replace

    par = generate_clean_pairs(seed=2, n=1)[0]
    banco = [replace(par.bank, amount=par.bank.amount - 1)]

    resultados = ExactMatcher().resolve(pool(bank=banco, ledger=[par.ledger])).resolutions

    assert resultados == []


def test_resultado_registra_a_regra():
    pares = generate_clean_pairs(seed=2, n=1)
    r = (
        ExactMatcher()
        .resolve(pool(bank=[pares[0].bank], ledger=[pares[0].ledger]))
        .resolutions[0]
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
        .resolve(pool(bank=[par.bank], ledger=[par.ledger, gemeo]))
        .resolutions
    )

    assert len(resultados) == 1
