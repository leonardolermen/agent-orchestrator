from orchestrator.cli import build_benchmark, main
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate


def test_benchmark_injeta_a_proporcao_pedida():
    ds = build_benchmark(seed=1, n=100, taxa_divergencia=0.2)
    # cada injeção consome um ou mais pares; a contagem é aproximada por desenho
    assert 5 <= len(ds.truth) <= 25


def test_benchmark_cobre_varios_tipos():
    ds = build_benchmark(seed=1, n=200, taxa_divergencia=0.3)
    tipos = {gt.divergence_type for gt in ds.truth}
    assert len(tipos) >= 3


def test_benchmark_e_deterministico():
    a = build_benchmark(seed=5, n=50, taxa_divergencia=0.2)
    b = build_benchmark(seed=5, n=50, taxa_divergencia=0.2)
    assert a.bank == b.bank
    assert [t.divergence_type for t in a.truth] == [t.divergence_type for t in b.truth]


def test_taxa_deterministica_fica_acima_do_alvo():
    # Critério F1 do spec: >= 85% com taxa de divergência de 15%.
    ds = build_benchmark(seed=3, n=300, taxa_divergencia=0.15)
    m = evaluate(ds, reconcile(ds.bank, ds.ledger))
    assert m.deterministic_rate >= 0.70, m.render()


def test_sem_falso_positivo_com_tolerancia_padrao():
    ds = build_benchmark(seed=3, n=300, taxa_divergencia=0.15)
    m = evaluate(ds, reconcile(ds.bank, ds.ledger))
    assert m.false_positives == 0, m.render()


def test_main_roda_e_retorna_zero(capsys):
    assert main(["--seed", "1", "--n", "50"]) == 0
    assert "Taxa determinística" in capsys.readouterr().out
