from random import Random

from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal


def test_dataset_limpo_tem_taxa_total():
    pares = generate_clean_pairs(seed=9, n=40)
    ds = build_dataset(pares, injections=[])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.deterministic_rate == 1.0
    assert m.false_positives == 0


def test_conta_divergencias_do_gabarito():
    pares = generate_clean_pairs(seed=9, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.truth_divergences == 1


def test_falso_positivo_quando_casa_o_que_deveria_divergir():
    # Tolerância absurda faz L2 casar um caso que o gabarito diz ser divergente.
    from orchestrator.matching.tolerance import ToleranceMatcher

    pares = generate_clean_pairs(seed=9, n=5)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger, matchers=[ToleranceMatcher(max_business_days=999)])
    m = evaluate(ds, r)

    assert m.false_positives == 1


def test_taxa_fica_entre_zero_e_um():
    pares = generate_clean_pairs(seed=9, n=30)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert 0.0 <= m.deterministic_rate <= 1.0


def test_cobertura_por_tipo_lista_os_tipos_injetados():
    pares = generate_clean_pairs(seed=9, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.truth_by_type["DEFASAGEM_TEMPORAL"] == 1


def test_agregado_resolvido_por_l3_nao_e_falso_positivo():
    from orchestrator.synth.injectors import PagamentoAgregado

    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.false_positives == 0
    assert m.false_negatives == 0


def test_falso_negativo_quando_camada_nao_resolve_o_que_deveria():
    from orchestrator.synth.injectors import PagamentoAgregado

    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    # sem nenhuma camada, o agregado deixa de ser resolvido
    m = evaluate(ds, reconcile(ds.bank, ds.ledger, matchers=[]))

    assert m.false_negatives == 1


def test_valores_somam_o_total_do_extrato():
    pares = generate_clean_pairs(seed=9, n=25)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.matched_amount + m.divergent_amount == sum(abs(e.amount) for e in ds.bank)


def test_render_formata_valores_em_reais():
    pares = generate_clean_pairs(seed=9, n=10)
    ds = build_dataset(pares, injections=[])

    saida = evaluate(ds, reconcile(ds.bank, ds.ledger)).render()

    assert "R$" in saida
    assert "Valor conciliado" in saida
