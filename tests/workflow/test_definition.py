import inspect

from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.definition import default_definition


def test_definicao_padrao_tem_as_tres_regras_num_stage():
    d = default_definition()

    assert d.id == "conciliacao"
    assert len(d.stages) == 1
    assert [r.name for r in d.stages[0].cascade] == ["L1", "L2", "L3", "revisor"]


def test_definicao_padrao_nao_gasta_dinheiro():
    # A propriedade que importa nunca foi "só existem regras" — foi "nada
    # aqui gasta dinheiro". Com o revisor na cascata a definição tem duas
    # classes, e trocar só a asserção sem trocar o nome transformaria um
    # guarda de dinheiro num guarda de forma.
    d = default_definition()

    classes = {r.cost_class for s in d.stages for r in s.cascade}
    assert CostClass.AGENTE not in classes


def test_definicao_padrao_inclui_o_revisor_por_ultimo():
    d = default_definition()

    cascata = d.stages[0].ordered()
    assert [r.name for r in cascata] == ["L1", "L2", "L3", "revisor"]
    assert cascata[-1].cost_class is CostClass.HUMANO


def test_definicao_padrao_sem_fila_nao_resolve_nada_pelo_revisor():
    # Sem fila, o revisor existe na cascata e é inerte. É isso que mantém a
    # CLI e o golden exatamente como estavam.
    from orchestrator.cli import build_benchmark
    from orchestrator.matching.engine import reconcile
    from orchestrator.workflow.cost_class import CostClass as C

    ds = build_benchmark(seed=1, n=60, taxa_divergencia=0.15)
    r = reconcile(ds.bank, ds.ledger)

    assert r.matches_by_class.get(C.HUMANO, []) == []
    assert r.matches_by_resolver["revisor"] == 0


def test_a_fabrica_padrao_declara_o_parametro_fila():
    # `orchestrator.api.app._construir_definicao` decide se repassa a fila
    # olhando o NOME literal `fila` na assinatura desta função — não há
    # import nem type check que amarre os dois lados. Renomear este parâmetro
    # faz a suíte inteira continuar verde (nenhum teste chama
    # `default_definition` por nome de parâmetro) enquanto `/runs` volta a
    # servir sempre uma fila vazia, silenciosamente — o mesmo defeito que a
    # Task 8 corrigiu. Este teste existe só para travar esse nome.
    assert "fila" in inspect.signature(default_definition).parameters


def test_stage_expoe_a_cascata_ordenada_por_classe_de_custo():
    # A ordenação acontece por stage, não global: um stage posterior não pode
    # ter seus resolvers embaralhados com os de um anterior.
    d = default_definition()
    cascata = d.stages[0].ordered()

    assert [r.cost_class for r in cascata] == sorted(r.cost_class for r in cascata)
