from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.definition import default_definition


def test_definicao_padrao_tem_as_tres_regras_num_stage():
    d = default_definition()

    assert d.id == "conciliacao"
    assert len(d.stages) == 1
    assert [r.name for r in d.stages[0].cascade] == ["L1", "L2", "L3"]


def test_definicao_padrao_nao_tem_agente():
    # O agente é opcional no conciliador e custa dinheiro. A definição padrão
    # — a que a API serve e a CLI executa — não o inclui, e é por isso que a
    # tela mostra uma LACUNA em vez de um selo sem medição.
    d = default_definition()

    classes = {r.cost_class for s in d.stages for r in s.cascade}
    assert classes == {CostClass.REGRA}


def test_stage_expoe_a_cascata_ordenada_por_classe_de_custo():
    # A ordenação acontece por stage, não global: um stage posterior não pode
    # ter seus resolvers embaralhados com os de um anterior.
    d = default_definition()
    cascata = d.stages[0].ordered()

    assert [r.cost_class for r in cascata] == sorted(r.cost_class for r in cascata)
