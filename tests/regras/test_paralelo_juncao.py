"""Duplicar em ramos e reunir os ramos. O que o roteamento NÃO faz.

`condicao` e `tabela` ROTEIAM: cada item vai para um ramo. Isso não cobre o caso
mais comum de paralelismo —

        ┌─→ checagem de fraude ─┐
    ─── ┤                       ├─→ junção ───
        └─→ checagem de KYC ────┘

— em que TODA transação passa pelas duas. Nenhum roteador faz isso, porque
roteador escolhe, e escolher é exatamente o que não se quer aqui.
"""

from dataclasses import dataclass

import pytest

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras import Juncao, Paralelo


@dataclass(frozen=True)
class Transacao:
    valor: int


def _pool(kinds_e_ids) -> WorkSet:
    return WorkSet(
        items=tuple(
            WorkItem(id=i, kind=k, payload=Transacao(10), origem="t")
            for k, i in kinds_e_ids
        )
    )


# --- paralelo ---------------------------------------------------------------


def test_todo_item_vai_para_TODOS_os_ramos():
    work = _pool([("transacao", "t1"), ("transacao", "t2")])

    saida = Paralelo(kind="transacao", ramos=("fraude", "kyc")).resolve(work)

    assert sorted((i.id, i.kind) for i in saida.produced) == [
        ("t1+fraude", "fraude"),
        ("t1+kyc", "kyc"),
        ("t2+fraude", "fraude"),
        ("t2+kyc", "kyc"),
    ]


def test_o_original_SAI_do_pool():
    """Consome e produz em conjunção (§3.1). Não consumir deixaria o original
    disputando os degraus de baixo junto com as cópias dele."""
    work = _pool([("transacao", "t1")])

    saida = Paralelo(kind="transacao", ramos=("a", "b")).resolve(work)

    assert [sorted(r.item_ids) for r in saida.resolutions] == [["t1"]]


def test_as_copias_compartilham_o_payload():
    # Ele é congelado, então compartilhar é seguro e evita N cópias de um dado
    # que ninguém vai mudar.
    original = Transacao(99)
    work = WorkSet(
        items=(WorkItem(id="t1", kind="transacao", payload=original, origem="t"),)
    )

    saida = Paralelo(kind="transacao", ramos=("a", "b")).resolve(work)

    assert all(i.payload is original for i in saida.produced)


def test_um_ramo_so_e_recusado():
    # Abrir em um ramo só é trocar o kind e nada mais — para isso existe a
    # `condicao`, que ao menos diz sob que condição.
    with pytest.raises(ValueError, match="ramo"):
        Paralelo(kind="transacao", ramos=("a",))


def test_ramo_repetido_e_recusado():
    with pytest.raises(ValueError, match="repetido"):
        Paralelo(kind="transacao", ramos=("a", "a"))


def test_ramo_igual_a_entrada_e_recusado():
    with pytest.raises(ValueError, match="a si mesmo"):
        Paralelo(kind="transacao", ramos=("transacao", "a"))


def test_declara_os_ramos_antes_de_rodar():
    d = Paralelo(kind="transacao", ramos=("fraude", "kyc")).describe()

    assert d.consome == frozenset({"transacao"})
    assert d.produz == frozenset({"fraude", "kyc"})


# --- junção -----------------------------------------------------------------


def test_reune_os_ramos_de_um_mesmo_item():
    work = _pool([("fraude", "t1+fraude"), ("kyc", "t1+kyc")])

    saida = Juncao(ramos=("fraude", "kyc"), produz="avaliado").resolve(work)

    assert [sorted(r.item_ids) for r in saida.resolutions] == [["t1+fraude", "t1+kyc"]]
    assert [(i.id, i.kind) for i in saida.produced] == [("t1+avaliado", "avaliado")]


def test_NAO_junta_pela_metade():
    """A escolha mais conservadora possível. Juntar com um ramo faltando
    produziria um item que PARECE completo e não é, e o degrau de baixo
    trabalharia sobre uma junção que perdeu um lado sem dizer. O que sobra fica
    no pool e aparece na lacuna, contado."""
    work = _pool([("fraude", "t1+fraude")])

    saida = Juncao(ramos=("fraude", "kyc"), produz="avaliado").resolve(work)

    assert saida.resolutions == []
    assert saida.produced == ()


def test_itens_de_origens_diferentes_nao_se_misturam():
    work = _pool(
        [
            ("fraude", "t1+fraude"),
            ("kyc", "t1+kyc"),
            ("fraude", "t2+fraude"),
        ]
    )

    saida = Juncao(ramos=("fraude", "kyc"), produz="avaliado").resolve(work)

    # `t2` só tem um ramo: não junta. `t1` tem os dois.
    assert len(saida.resolutions) == 1
    assert saida.produced[0].id == "t1+avaliado"


def test_produzir_um_ramo_que_consome_e_recusado():
    with pytest.raises(ValueError, match="a si mesmo"):
        Juncao(ramos=("a", "b"), produz="a")


def test_juntar_um_ramo_so_e_recusado():
    with pytest.raises(ValueError, match="ramo"):
        Juncao(ramos=("a",), produz="x")


# --- os dois juntos, que é o desenho do começo ------------------------------


def test_abrir_e_reunir_de_ponta_a_ponta():
    work = _pool([("transacao", "t1"), ("transacao", "t2")])

    aberto = Paralelo(kind="transacao", ramos=("fraude", "kyc")).resolve(work)
    depois = WorkSet(items=aberto.produced)
    junto = Juncao(ramos=("fraude", "kyc"), produz="avaliado").resolve(depois)

    assert sorted(i.id for i in junto.produced) == ["t1+avaliado", "t2+avaliado"]


def test_um_item_que_JA_ramificou_antes_reune_pelo_ramo_MAIS_RECENTE():
    """`rsplit` e não `split`: um id de origem pode conter o separador, e
    quebrar no primeiro reuniria itens que não são o mesmo."""
    work = _pool([("a", "t1+lote+a"), ("b", "t1+lote+b")])

    saida = Juncao(ramos=("a", "b"), produz="x").resolve(work)

    assert saida.produced[0].id == "t1+lote+x"
