"""O pool genérico. Nenhum teste aqui menciona conciliação, e é o ponto.

Este arquivo é a prova executável de que `kernel/work.py` não sabe o que é um
lançamento bancário: ele usa payloads inventados (`str`, `int`) porque o kernel
nunca os inspeciona. Se um teste daqui precisar importar de `models.py`, a
de-domainização falhou.
"""

import pytest

from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.work import WorkItem, WorkSet


def _pool(*ids: str, kind: str = "coisa") -> WorkSet:
    return WorkSet(items=tuple(WorkItem(id=i, kind=kind, payload=i) for i in ids))


def _res(*ids: str) -> Resolution:
    return Resolution(item_ids=frozenset(ids), produced_by="t", rule="teste")


def test_item_exige_id_e_kind():
    # Id vazio não identifica nada, e dois itens de id "" fariam `without`
    # remover os dois ao resolver um.
    with pytest.raises(ValueError):
        WorkItem(id="", kind="coisa", payload=None)
    with pytest.raises(ValueError):
        WorkItem(id="a", kind="", payload=None)


def test_pool_recusa_id_repetido():
    """A guarda que torna a disjunção de ids estrutural.

    `metrics` separa lado intersectando `Resolution.item_ids` com os ids de
    cada lado, e isso só está correto se nenhum id se repetir entre lados. Esta
    guarda é o que transforma aquela suposição em invariante — ver o docstring
    de `models.pool`.
    """
    with pytest.raises(ValueError, match="id repetido"):
        WorkSet(
            items=(
                WorkItem(id="x", kind="a", payload=1),
                WorkItem(id="x", kind="b", payload=2),
            )
        )


def test_of_kind_preserva_a_ordem_de_entrada():
    # A ordem não é estética: o golden de 12 sementes depende da ordem em que
    # as divergências saem, e ela vem daqui.
    work = WorkSet(
        items=(
            WorkItem(id="b1", kind="banco", payload=1),
            WorkItem(id="l1", kind="contabil", payload=2),
            WorkItem(id="b2", kind="banco", payload=3),
        )
    )
    assert [i.id for i in work.of_kind("banco")] == ["b1", "b2"]
    assert work.payloads("contabil") == (2,)
    assert work.of_kind("inexistente") == ()


def test_without_remove_exatamente_os_ids_citados():
    work = _pool("a", "b", "c")

    restante = work.without([_res("a", "c")])

    assert [i.id for i in restante.items] == ["b"]


def test_without_sem_resolucao_nenhuma_devolve_o_mesmo_conteudo():
    work = _pool("a", "b")
    assert work.without([]) == work


def test_without_nao_muta_o_original():
    # WorkSet é passado de resolver em resolver. Se `without` mutasse, um
    # resolver enxergaria o pool que o próximo já alterou.
    work = _pool("a", "b")

    restante = work.without([_res("a")])

    assert restante is not work
    assert len(work.items) == 2


def test_without_ignora_id_que_nao_esta_no_pool():
    """Silêncio, não erro.

    Uma resolução pode citar um id que outro resolver já consumiu na mesma
    passagem. Levantar aqui transformaria uma corrida benigna em falha do
    fechamento inteiro. Quem PRECISA recusar id fantasma é o domínio, na
    construção da resolução — ver `models.conciliacao`.
    """
    work = _pool("a")

    assert work.without([_res("a", "fantasma")]).items == ()


def test_items_e_tupla_nao_lista():
    """Imutabilidade de verdade, não só na casca.

    `Dataset` documenta que `frozen=True` não torna suas LISTAS imutáveis. Um
    `WorkSet` com lista teria o mesmo buraco, e um resolver poderia mudar o
    pool por baixo do motor.
    """
    assert isinstance(_pool("a").items, tuple)


def test_com_acrescenta_preservando_ordem():
    """A ordem é contrato, não estética: o golden de 12 sementes depende dela.

    Item produzido entra no FIM. Entrar no começo faria um item novo ser visto
    antes de itens que já estavam esperando, e a ordem de saída mudaria por
    causa de quem produziu, não de quem chegou.
    """
    pool = _pool("a", "b")

    novo = pool.com([WorkItem(id="c", kind="coisa", payload="c", origem="escritor")])

    assert [i.id for i in novo.items] == ["a", "b", "c"]
    # O pool original não muda: `WorkSet` é imutável de verdade.
    assert [i.id for i in pool.items] == ["a", "b"]


def test_com_vazio_devolve_o_mesmo_pool():
    """Simetria com `without()`, que já devolve `self` quando nada foi
    consumido. Sem isso, uma ronda sem produção alocaria um pool novo por
    stage, e o laço da Task 5 chama isto por stage por ronda."""
    pool = _pool("a")

    assert pool.com([]) is pool


def test_com_recusa_id_que_ja_existe():
    """A guarda de id repetido de `__post_init__` vale para produção também.

    Um resolver que produz um id já presente faria `without()` remover os dois
    ao resolver um — exatamente o defeito que `test_pool_recusa_id_repetido`
    previne na construção.
    """
    pool = _pool("a")

    with pytest.raises(ValueError, match="id repetido"):
        pool.com([WorkItem(id="a", kind="coisa", payload="outro")])


def test_origem_default_e_vazia():
    """Item que veio da fonte não tem origem — ninguém o produziu. String
    vazia, não `None`: o campo é sempre legível, e serializar `None` num
    trace obrigaria todo consumidor a tratar dois casos."""
    assert WorkItem(id="a", kind="coisa", payload=1).origem == ""
    assert WorkItem(id="b", kind="coisa", payload=1, origem="x").origem == "x"
