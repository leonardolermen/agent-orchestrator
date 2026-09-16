from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput


def test_saida_vazia_e_o_default():
    # Um resolver que não resolveu nada é caso normal, não excepcional: ele
    # devolve ResolverOutput() e não precisa saber montar três coleções.
    saida = ResolverOutput()

    assert saida.resolutions == []
    assert saida.proposals == []
    assert saida.cost == Cost.zero()


def test_matches_e_proposals_sao_campos_separados():
    # O dia em que virarem um campo só com flag, a garantia de tipo que
    # impede conciliação fantasma some. Este teste existe para quebrar nesse
    # dia.
    m = Resolution(
                        item_ids=frozenset({"b1"})
                        | frozenset({"l1"}),
                        produced_by="L1",
        rule="teste",
    )
    saida = ResolverOutput(resolutions=[m])

    assert saida.resolutions == [m]
    assert saida.proposals == []


def test_descricao_carrega_a_classe_de_custo():
    d = ResolverDescription(
        name="L1", cost_class=CostClass.REGRA, summary="documento, valor e data iguais"
    )

    assert d.cost_class is CostClass.REGRA
    assert d.name == "L1"
