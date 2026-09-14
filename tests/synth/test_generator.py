from orchestrator.synth.generator import build_dataset, generate_clean_pairs


def test_gera_a_quantidade_pedida():
    pares = generate_clean_pairs(seed=42, n=50)
    assert len(pares) == 50


def test_par_limpo_concilia_perfeitamente():
    for p in generate_clean_pairs(seed=1, n=20):
        # débito bancário negativo espelha o líquido contábil positivo
        assert p.bank.amount == -p.ledger.net_amount
        assert p.bank.date == p.ledger.cash_date
        assert p.bank.document == p.ledger.document


def test_determinismo_por_semente():
    a = generate_clean_pairs(seed=7, n=30)
    b = generate_clean_pairs(seed=7, n=30)
    assert a == b


def test_sementes_diferentes_geram_datasets_diferentes():
    a = generate_clean_pairs(seed=7, n=30)
    b = generate_clean_pairs(seed=8, n=30)
    assert a != b


def test_ids_sao_unicos():
    pares = generate_clean_pairs(seed=3, n=100)
    assert len({p.bank.id for p in pares}) == 100
    assert len({p.ledger.id for p in pares}) == 100


def test_build_dataset_sem_injecoes_devolve_tudo_limpo():
    pares = generate_clean_pairs(seed=5, n=10)
    ds = build_dataset(pares, injections=[])
    assert len(ds.bank) == 10
    assert len(ds.ledger) == 10
    assert ds.truth == []


def test_generate_rejeita_n_invalido():
    # Lista vazia em silêncio zeraria toda métrica calculada em cima dela.
    import pytest

    with pytest.raises(ValueError):
        generate_clean_pairs(seed=1, n=0)
    with pytest.raises(ValueError):
        generate_clean_pairs(seed=1, n=-5)
