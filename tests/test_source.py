"""`Source`: a origem do trabalho, com identidade reproduzível."""

from orchestrator.synth.benchmark import SyntheticSource, build_benchmark


def test_o_ref_identifica_a_ENTRADA_e_nao_a_execucao():
    """Duas execuções sobre a mesma entrada têm o mesmo `ref`.

    É o que permite ao `ReplayResume` (M7) casar as decisões humanas já tomadas
    com o trabalho de agora. Se o `ref` variasse por execução, retomar seria
    começar do zero.
    """
    a = SyntheticSource(seed=1, n=30, taxa_divergencia=0.15)
    b = SyntheticSource(seed=1, n=30, taxa_divergencia=0.15)

    assert a.ref == b.ref == "synth:s1-n30-t0.15"


def test_entradas_diferentes_tem_refs_diferentes():
    assert SyntheticSource(seed=1).ref != SyntheticSource(seed=2).ref
    assert SyntheticSource(n=30).ref != SyntheticSource(n=40).ref


def test_o_prefixo_abre_espaco_para_as_outras_fontes():
    """`synth:` não é decoração: é o que permite `file:`, `erp:` conviverem no
    mesmo campo sem ambiguidade."""
    assert SyntheticSource().ref.startswith("synth:")


def test_load_devolve_so_o_trabalho_sem_gabarito():
    """O gabarito é insumo de AVALIAÇÃO, e o motor não deve recebê-lo.

    É por isso que `dataset()` e `load()` são métodos separados — e é por isso
    que um `Source` de dado real terá só o segundo.
    """
    fonte = SyntheticSource(seed=1, n=20, taxa_divergencia=0.15)

    work = fonte.load()

    assert not hasattr(work, "truth")
    assert len(work.items) == len(fonte.dataset().bank) + len(fonte.dataset().ledger)


def test_o_pool_carrega_os_dois_lados_da_conciliacao():
    fonte = SyntheticSource(seed=1, n=20, taxa_divergencia=0.15)

    kinds = {i.kind for i in fonte.load().items}

    assert kinds == {"banco", "contabil"}


def test_dataset_e_o_mesmo_que_build_benchmark_produz():
    """A fonte não reimplementa o gerador — ela o expõe.

    Se reimplementasse, o golden de 12 sementes mediria uma coisa e a API
    executaria outra.
    """
    fonte = SyntheticSource(seed=7, n=40, taxa_divergencia=0.2)

    direto = build_benchmark(7, 40, 0.2)

    assert [e.id for e in fonte.dataset().bank] == [e.id for e in direto.bank]
