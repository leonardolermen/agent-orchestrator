"""O de-para que escolhe o ramo — a `condicao` com muitas saídas."""

from dataclasses import dataclass

import pytest

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras.tabela import Tabela


@dataclass(frozen=True)
class Cliente:
    tipo: str


def _pool(*tipos: str) -> WorkSet:
    return WorkSet(
        items=tuple(
            WorkItem(id=f"c{i}", kind="cliente", payload=Cliente(t), origem="t")
            for i, t in enumerate(tipos)
        )
    )


def _regra(**kw) -> Tabela:
    base = dict(kind="cliente", campo="tipo", de_para=("PJ=empresa", "PF=pessoa"))
    return Tabela(**{**base, **kw})


def test_o_valor_escolhe_o_ramo():
    saida = _regra().resolve(_pool("PJ", "PF"))

    assert [(i.id, i.kind) for i in saida.produced] == [
        ("c0+empresa", "empresa"),
        ("c1+pessoa", "pessoa"),
    ]


def test_consome_e_produz_em_conjuncao():
    # A §3.1, igual à `condicao`: transformar é consumir A **e** produzir B.
    saida = _regra().resolve(_pool("PJ"))

    assert [sorted(r.item_ids) for r in saida.resolutions] == [["c0"]]
    assert len(saida.produced) == 1


def test_valor_FORA_da_tabela_nao_e_tocado():
    """Um ramo "resto" implícito esconderia a diferença entre "classifiquei
    como resto" e "não soube classificar" — e essa diferença é a que mais custa
    caro neste produto. O item fica no pool para o próximo degrau."""
    saida = _regra().resolve(_pool("MEI"))

    assert saida.resolutions == []
    assert saida.produced == ()


def test_declara_TODOS_os_destinos_antes_de_rodar():
    """Não só os que algum item vai usar. Um destino que só aparece quando o
    dado certo chega é um beco sem saída descoberto em produção."""
    d = _regra().describe()

    assert d.consome == frozenset({"cliente"})
    assert d.produz == frozenset({"empresa", "pessoa"})


def test_o_payload_atravessa_intacto():
    # Rotear não enriquece: o payload é congelado, e produzir um dict no lugar
    # faria todo bloco tipado depois parar de funcionar em silêncio.
    original = Cliente("PJ")
    work = WorkSet(
        items=(WorkItem(id="c0", kind="cliente", payload=original, origem="t"),)
    )

    assert _regra().resolve(work).produced[0].payload is original


def test_rota_para_o_proprio_kind_e_recusada():
    with pytest.raises(ValueError, match="a si mesmo"):
        _regra(de_para=("PJ=cliente",))


def test_tabela_vazia_e_recusada():
    with pytest.raises(ValueError):
        _regra(de_para=())


def test_roda_sobre_dict():
    work = WorkSet(
        items=(WorkItem(id="c0", kind="cliente", payload={"tipo": "PF"}, origem="t"),)
    )

    assert _regra().resolve(work).produced[0].kind == "pessoa"
