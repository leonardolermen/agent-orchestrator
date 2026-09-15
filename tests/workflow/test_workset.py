from orchestrator.models import MatchResult
from orchestrator.synth.generator import generate_clean_pairs
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.workset import WorkSet


def _duas_pontas():
    """Dois lançamentos de cada lado, pelo mesmo gerador que o resto da suíte usa."""
    pares = generate_clean_pairs(seed=2, n=2)
    return [p.bank for p in pares], [p.ledger for p in pares]


def test_ordem_das_classes_de_custo_e_regra_agente_humano():
    # A ordem é o produto, não um detalhe: é ela que impede um agente de
    # rodar antes de uma regra.
    assert CostClass.REGRA < CostClass.AGENTE < CostClass.HUMANO


def test_as_divergences_gera_uma_por_orfao_banco_primeiro():
    banco, contabil = _duas_pontas()
    work = WorkSet(bank=banco[:1], ledger=contabil[:1])

    divergencias = work.as_divergences()

    assert [d.id for d in divergencias] == [
        f"d-b-{banco[0].id}",
        f"d-l-{contabil[0].id}",
    ]
    assert divergencias[0].bank_ids == frozenset({banco[0].id})
    assert divergencias[0].ledger_ids == frozenset()
    assert divergencias[1].bank_ids == frozenset()
    assert divergencias[1].ledger_ids == frozenset({contabil[0].id})


def test_without_remove_os_dois_lados_do_vinculo():
    banco, contabil = _duas_pontas()
    work = WorkSet(bank=banco, ledger=contabil)
    m = MatchResult(
        bank_ids=frozenset({banco[0].id}),
        ledger_ids=frozenset({contabil[0].id}),
        layer="L1",
        rule="teste",
    )

    restante = work.without([m])

    assert [e.id for e in restante.bank] == [banco[1].id]
    assert [e.id for e in restante.ledger] == [contabil[1].id]


def test_without_sem_vinculo_nenhum_devolve_o_mesmo_conteudo():
    banco, contabil = _duas_pontas()

    restante = WorkSet(bank=banco, ledger=contabil).without([])

    assert [e.id for e in restante.bank] == [e.id for e in banco]
    assert [e.id for e in restante.ledger] == [e.id for e in contabil]


def test_without_devolve_objeto_novo_e_nao_muta_o_original():
    # WorkSet é passado de resolver em resolver. Se `without` mutasse, um
    # resolver enxergaria o pool que o próximo já alterou.
    banco, contabil = _duas_pontas()
    work = WorkSet(bank=banco, ledger=contabil)
    m = MatchResult(
        bank_ids=frozenset({banco[0].id}),
        ledger_ids=frozenset({contabil[0].id}),
        layer="L1",
        rule="teste",
    )

    restante = work.without([m])

    assert restante is not work
    assert len(work.bank) == 2
