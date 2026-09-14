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


def test_build_dataset_remove_originais_em_fan_out():
    # Devolução de fundos: um par consumido, três pernas devolvidas com ids
    # novos. Se o original sobreviver, vira divergência sem gabarito.
    from dataclasses import replace

    from orchestrator.synth.dataset import GroundTruth, InjectionResult
    from orchestrator.taxonomy import DivergenceType

    pares = generate_clean_pairs(seed=8, n=3)
    p = pares[0]
    pernas = [replace(p.bank, id=f"{p.bank.id}-{s}") for s in ("a", "b", "c")]
    inj = InjectionResult(
        consumed=(p,),
        bank=pernas,
        ledger=[p.ledger],
        truth=GroundTruth(
            divergence_type=DivergenceType.DEVOLUCAO_FUNDOS,
            bank_ids=frozenset(e.id for e in pernas),
            ledger_ids=frozenset({p.ledger.id}),
            explanation="devolvida e reenviada",
        ),
    )

    ds = build_dataset(pares, injections=[inj])

    assert len(ds.bank) == 5  # dois pares intactos mais as três pernas
    assert p.bank.id not in {e.id for e in ds.bank}


def test_build_dataset_remove_originais_em_fan_in():
    # Pagamento agregado: três pares consumidos, um lançamento devolvido. Se os
    # outros dois sobreviverem, o dataset soma dinheiro que não existe.
    from dataclasses import replace

    from orchestrator.synth.dataset import GroundTruth, InjectionResult
    from orchestrator.taxonomy import DivergenceType

    pares = generate_clean_pairs(seed=8, n=3)
    total = sum(p.ledger.net_amount for p in pares)
    agregado = replace(pares[0].bank, amount=-total)
    inj = InjectionResult(
        consumed=tuple(pares),
        bank=[agregado],
        ledger=[p.ledger for p in pares],
        truth=GroundTruth(
            divergence_type=DivergenceType.PAGAMENTO_AGREGADO,
            bank_ids=frozenset({agregado.id}),
            ledger_ids=frozenset(p.ledger.id for p in pares),
            explanation="lote de três documentos",
            deterministic_expected=True,
        ),
    )

    ds = build_dataset(pares, injections=[inj])

    assert len(ds.bank) == 1
    assert sum(abs(e.amount) for e in ds.bank) == total
