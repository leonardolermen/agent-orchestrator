from datetime import date

import pytest

from orchestrator.kernel.work import WorkSet
from orchestrator.models import (
    BankEntry,
    LedgerEntry,
    conciliacao,
    divergencias,
    lados,
    pool,
)


def _bank(id_: str = "b1", amount: int = -10000) -> BankEntry:
    return BankEntry(
        id=id_,
        date=date(2026, 9, 14),
        amount=amount,
        description="PAGTO FORNECEDOR",
        counterparty="ACME LTDA",
        document="NF-1001",
    )


def _ledger(id_: str = "l1", net: int = 10000) -> LedgerEntry:
    return LedgerEntry(
        id=id_,
        accrual_date=date(2026, 9, 10),
        cash_date=date(2026, 9, 14),
        gross_amount=net,
        net_amount=net,
        account="2.1.1.01",
        cost_center="ADM",
        document="NF-1001",
        supplier="ACME LTDA",
    )


def test_entradas_sao_imutaveis():
    b = _bank()
    with pytest.raises(AttributeError):
        b.amount = 1  # type: ignore[misc]


def _pool() -> "WorkSet":
    return pool(bank=[_bank("b1")], ledger=[_ledger("l1"), _ledger("l2")])


def test_conciliacao_unifica_os_ids_dos_dois_lados():
    m = conciliacao(
        _pool(),
        frozenset({"b1", "l1", "l2"}),
        produced_by="L3",
        rule="soma de líquidos igual ao crédito",
        evidence={"soma": 10000},
    )
    assert m.item_ids == frozenset({"b1", "l1", "l2"})
    assert m.produced_by == "L3"


def test_conciliacao_rejeita_vinculo_de_um_lado_so():
    """A cardinalidade do domínio, no único lugar onde ela é expressável.

    `MatchResult.__post_init__` exigia um id de cada lado. `Resolution` não
    pode — um domínio de um lado só é legítimo —, então a regra desce para cá.
    Não é afrouxamento: todo produtor de vínculo de conciliação passa por aqui.
    """
    with pytest.raises(ValueError, match="pelo menos um id de cada lado"):
        conciliacao(_pool(), frozenset({"l1", "l2"}), produced_by="L1", rule="")


def test_conciliacao_rejeita_id_que_nao_esta_no_pool():
    """A guarda contra id fantasma, na CONSTRUÇÃO.

    Antes ela só existia em `metrics.evaluate`, onde protegia a métrica
    intersectando com os ids do dataset. Aqui protege o ESTADO: um resolver de
    terceiro com bug não consegue mais encolher o pool com um id inventado.
    """
    with pytest.raises(ValueError, match="não estão no pool"):
        conciliacao(_pool(), frozenset({"b1", "inventado"}), produced_by="L1", rule="")


def test_o_lado_vem_do_pool_e_nao_do_chamador():
    """O chamador não consegue nem errar o lado, nem mentir sobre ele.

    Com `item_ids` unificado, um resolver que trocasse os dois lados produziria
    exatamente a mesma `Resolution` — e nenhum teste conseguiria notar. Por
    isso `conciliacao` deriva o lado de `lados(work, ...)`, e é essa derivação,
    não a disciplina de quem chama, que faz a troca ser inexprimível.
    """
    work = _pool()
    assert lados(work, frozenset({"b1", "l1"})) == (
        frozenset({"b1"}),
        frozenset({"l1"}),
    )
    # Um id fora do pool não entra em nenhum dos dois lados. Quem chama decide
    # se isso é obsolescência (o revisor: silêncio) ou erro (conciliacao: raise).
    assert lados(work, frozenset({"sumiu"})) == (frozenset(), frozenset())


def test_pool_preserva_a_ordem_banco_depois_contabil():
    # `divergencias()` percorre `items` na ordem, e o golden de 12 sementes
    # pina a ordem em que as divergências saem.
    work = _pool()
    assert [i.id for i in work.items] == ["b1", "l1", "l2"]


def test_divergencias_uma_por_orfao_banco_primeiro():
    work = pool(bank=[_bank("b1")], ledger=[_ledger("l1")])

    divs = divergencias(work)

    assert [d.id for d in divs] == ["d-b-b1", "d-l-l1"]
    assert divs[0].bank_ids == frozenset({"b1"})
    assert divs[0].ledger_ids == frozenset()
    assert divs[1].bank_ids == frozenset()
    assert divs[1].ledger_ids == frozenset({"l1"})


def test_pool_recusa_id_repetido_entre_os_dois_lados():
    """A disjunção banco/contábil, garantida de graça pelo kernel.

    `metrics` separa lado intersectando `item_ids` com os ids de cada lado, o
    que só está correto se nenhum id bancário for igual a um contábil. Antes
    era suposição sobre o gerador (prefixos `b`/`l`); agora é invariante, e
    quem a impõe é `WorkSet.__post_init__`.
    """
    with pytest.raises(ValueError, match="id repetido"):
        pool(bank=[_bank("x")], ledger=[_ledger("x")])
