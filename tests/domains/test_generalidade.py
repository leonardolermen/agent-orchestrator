"""O teste de generalidade: a abstração serve a mais de um domínio?

Este arquivo é o substituto de engenharia para a regra dos três usos, que o
dono do projeto suspendeu em 2026-09-16 (§1.3 do spec de migração). A regra
existia porque abstração desenhada a partir de uma instância costuma estar
errada — e isso continua verdade independentemente de quem decide.

O substituto barato não é esperar três clientes: é escrever as outras duas
instâncias como esqueletos executáveis ENQUANTO o kernel ainda está mole. Cada
atrito que elas encontram vira uma correção de um dia em vez de uma descoberta
de um mês.

**Já funcionou.** Escrever estes dois domínios achou dois defeitos que nenhuma
análise prévia tinha visto:

  1. `Proposal.tipo` era `DivergenceType` — a taxonomia de conciliação dentro
     do tipo que todo resolver de classe paga devolve. Um domínio novo não
     conseguia propor nada.
  2. `Proposal.divergence_id` — "divergência" é vocabulário de conciliação. Um
     pedido de compra não é uma divergência.

Os dois foram achados na PRIMEIRA linha de código de domínio, não por leitura.
"""

from orchestrator.domains.procurement.workflow import (
    BuscadorDeFornecedor,
    ComprasAnteriores,
    Fornecedor,
    FornecedorPreferido,
    Requisicao,
)
from orchestrator.domains.procurement.workflow import definition as def_procurement
from orchestrator.domains.procurement.workflow import pool as pool_procurement
from orchestrator.domains.swe.workflow import Issue
from orchestrator.domains.swe.workflow import definition as def_swe
from orchestrator.domains.swe.workflow import pool as pool_swe
from orchestrator.kernel.cost import CostClass
from orchestrator.runtime.engine import execute


def _mercado():
    reqs = [
        Requisicao("r1", "papel", 10),
        Requisicao("r2", "toner", 2),
        Requisicao("r3", "drone", 1),
    ]
    forns = [
        Fornecedor("f1", "Papelaria", frozenset({"papel"}), preferido=True),
        Fornecedor("f2", "InfoSupri", frozenset({"toner"})),
        Fornecedor("f3", "Generica", frozenset({"papel"})),
    ]
    return reqs, forns


# ---------------------------------------------------------------------------
# Procurement: cascata completa, cardinalidade e vocabulário diferentes
# ---------------------------------------------------------------------------


def test_procurement_roda_a_cascata_inteira_do_barato_ao_caro():
    reqs, forns = _mercado()

    r = execute(def_procurement(), pool_procurement(reqs, forns))

    # As duas regras resolveram o que sabiam, de graça.
    assert {x.produced_by for x in r.resolutions} == {"preferido", "anteriores"}
    # O agente só propôs para o que sobrou, e proposta NÃO resolve.
    assert [p.item_id for p in r.proposals] == ["r3"]
    assert "r3" in r.unresolved.ids()


def test_procurement_a_decisao_humana_fecha_o_que_a_regra_nao_fechou():
    reqs, forns = _mercado()

    r = execute(def_procurement(aprovacoes={"r3": "f3"}), pool_procurement(reqs, forns))

    assert r.unresolved.items == ()
    assert any(x.produced_by == "comprador" for x in r.resolutions)


def test_procurement_decisao_obsoleta_vira_silencio_nao_erro():
    """Mesma política que `RevisorHumano` aplica na conciliação, num resolver
    que não tem nada a ver com ela."""
    reqs, forns = _mercado()

    r = execute(
        def_procurement(aprovacoes={"r1": "f1", "nao-existe": "f3"}),
        pool_procurement(reqs, forns),
    )

    assert all(x.produced_by != "comprador" for x in r.resolutions)


def test_procurement_o_agente_nunca_devolve_resolucao():
    """A invariante nº 1 do §1.5, verificada fora da conciliação.

    Se ela só valesse para o `Investigator`, seria disciplina daquele arquivo.
    Vale porque `ResolverOutput` tem dois campos separados.
    """
    reqs, forns = _mercado()
    saida = BuscadorDeFornecedor().resolve(pool_procurement(reqs, forns))

    assert saida.resolutions == []
    assert saida.proposals


def test_procurement_ordem_de_custo_vale_fora_da_conciliacao():
    cascata = def_procurement().stages[0].ordered()
    assert [r.cost_class for r in cascata] == sorted(r.cost_class for r in cascata)
    assert cascata[0].cost_class is CostClass.REGRA
    assert cascata[-1].cost_class is CostClass.HUMANO


def test_procurement_regra_barata_roda_antes_da_generica():
    """`sorted` é estável: dentro de uma classe, vence a ordem que o autor
    escreveu. `preferido` e `anteriores` são ambos REGRA, e `preferido` tem de
    ficar com o fornecedor preferido."""
    reqs, forns = _mercado()
    work = pool_procurement(reqs, forns)

    preferido = FornecedorPreferido().resolve(work).resolutions
    restante = work.without(preferido)
    anteriores = ComprasAnteriores().resolve(restante).resolutions

    assert [sorted(x.item_ids) for x in preferido] == [["f1", "r1"]]
    assert all("f1" not in x.item_ids for x in anteriores)


# ---------------------------------------------------------------------------
# Software Eng: o CASO DEGENERADO — cascata sem nenhum resolver de classe REGRA
# ---------------------------------------------------------------------------


def test_swe_cascata_sem_nenhuma_regra_barata_roda():
    """O teste mais duro da abstração.

    Se o kernel só soubesse expressar cascatas que começam com regra, ele não
    seria genérico — seria a conciliação com nomes trocados. O spec de
    composição §1.3 chama este de "o caso degenerado", e diz que o fato de ele
    caber sem forçar é o teste de generalidade.
    """
    issues = [Issue("i1", "Erro ao salvar", "..."), Issue("i2", "Export", "...")]

    r = execute(def_swe(), pool_swe(issues))

    assert [p.tipo for p in r.proposals] == ["BUG", "FEATURE"]
    assert r.resolutions == []
    # Nada resolveu, então tudo continua pendente. Não é falha: é a LACUNA,
    # declarada em vez de escondida.
    assert len(r.unresolved.items) == 2


def test_swe_nao_produz_a_chave_REGRA_em_resolutions_by_class():
    """A guarda que `metrics` documenta e que nunca tinha sido exercida.

    O comentário em `metrics.evaluate` diz que o default de `de_regra` é `[]` e
    não `result.matches` porque "uma cascata sem resolver REGRA nenhum
    legitimamente não tem match determinístico algum". Até este domínio existir,
    nenhum caso real produzia essa situação — a guarda estava correta e não
    testada.
    """
    r = execute(def_swe(), pool_swe([Issue("i1", "Erro", "...")]))

    assert CostClass.REGRA not in r.resolutions_by_class


def test_swe_um_kind_so_e_suficiente():
    """A assimetria da conciliação (dois lados) é do domínio, não do kernel."""
    work = pool_swe([Issue("i1", "x", "y")])

    assert {i.kind for i in work.items} == {"issue"}
    assert work.of_kind("issue")
