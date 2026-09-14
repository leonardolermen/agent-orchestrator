from random import Random

from orchestrator.matching.engine import default_matchers, reconcile
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal, DevolucaoFundos


def test_dataset_limpo_nao_gera_divergencia():
    pares = generate_clean_pairs(seed=8, n=30)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger)

    assert r.divergences == []
    assert len(r.matches) == 30


def test_camadas_sao_aplicadas_em_ordem():
    pares = generate_clean_pairs(seed=8, n=10)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger)

    # tudo limpo deve ser resolvido na camada mais barata
    assert {m.layer for m in r.matches} == {"L1"}


def test_defasagem_grande_vira_divergencia():
    pares = generate_clean_pairs(seed=8, n=5)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger)

    ids_divergentes = {i for d in r.divergences for i in d.bank_ids | d.ledger_ids}
    assert inj.bank[0].id in ids_divergentes


def test_devolucao_vira_divergencia_com_todas_as_pernas():
    pares = generate_clean_pairs(seed=8, n=5)
    inj = DevolucaoFundos().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger)

    ids_divergentes = {i for d in r.divergences for i in d.bank_ids}
    assert all(e.id in ids_divergentes for e in inj.bank)


def test_nenhum_lancamento_aparece_em_match_e_divergencia():
    pares = generate_clean_pairs(seed=8, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger)

    casados = {i for m in r.matches for i in m.bank_ids | m.ledger_ids}
    divergentes = {i for d in r.divergences for i in d.bank_ids | d.ledger_ids}
    assert casados & divergentes == set()


def test_matchers_sao_injetaveis():
    pares = generate_clean_pairs(seed=8, n=5)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger, matchers=[])

    assert r.matches == []
    assert len(r.divergences) > 0


def test_default_matchers_tem_tres_camadas():
    assert [m.layer for m in default_matchers()] == ["L1", "L2", "L3"]
