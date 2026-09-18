"""Mais de um degrau por workflow — e o que isso destrava.

Enquanto a composição montava uma etapa só, um bloco que ramifica não tinha
para onde ramificar: o ramo virava beco sem saída e só a `entrega` o salvava.
Com duas, o ramo tem degrau de verdade depois dele, e é isso que estes testes
fixam.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from orchestrator.authoring.composicao import (
    BlocoRegra,
    Composicao,
    Etapa,
    construir_composicao,
)
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime.engine import execute

AGORA = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _composicao(**kw) -> Composicao:
    base = dict(id="w", nome="W", gerado_em=AGORA)
    return Composicao(**{**base, **kw})


def _condicao(produz: str) -> BlocoRegra:
    return BlocoRegra(
        nome="condicao",
        parametros={
            "kind": "pedido",
            "campo": "valor",
            "teste": "maior",
            "valor": "1000",
            "produz": produz,
        },
    )


def _filtro(kind: str) -> BlocoRegra:
    return BlocoRegra(
        nome="filtro",
        parametros={"kind": kind, "campo": "valor", "teste": "preenchido"},
    )


# --- o açúcar e a forma geral ----------------------------------------------


def test_blocos_e_acucar_de_uma_etapa_so():
    """Todo chamador de hoje escreve `blocos=`, e nenhum precisou mudar.

    Mesma assimetria de `Task()` no kernel, que existe "para que quem chega do
    CrewAI encontre a palavra que espera".
    """
    c = _composicao(blocos=(BlocoRegra(nome="L1", parametros={}),))

    assert len(c.etapas) == 1
    assert c.etapas[0].nome == "W"
    assert len(c.blocos) == 1


def test_etapas_deriva_a_lista_achatada():
    """`blocos` continua sendo "todos os blocos" — derivado, nunca escrito em
    paralelo. É o que mantém os leitores de hoje corretos."""
    c = _composicao(
        etapas=(
            Etapa(nome="triagem", blocos=(_condicao("suspeito"),)),
            Etapa(nome="revisão", blocos=(_filtro("suspeito"),)),
        ),
        entrega=(),
    )

    assert [e.nome for e in c.etapas] == ["triagem", "revisão"]
    assert len(c.blocos) == 2


def test_os_dois_juntos_sao_recusados():
    with pytest.raises(ValueError, match="açúcar"):
        _composicao(
            blocos=(BlocoRegra(nome="L1", parametros={}),),
            etapas=(Etapa(nome="x", blocos=(BlocoRegra(nome="L2", parametros={}),)),),
        )


def test_etapa_vazia_e_recusada():
    # Um degrau vazio não roda e não produz, e ficaria no desenho parecendo que
    # faz alguma coisa.
    with pytest.raises(ValueError, match="sem bloco"):
        Etapa(nome="vazia", blocos=())


def test_os_MESMOS_blocos_em_um_degrau_ou_em_dois_sao_workflows_DIFERENTES():
    """E por isso têm versões diferentes.

    Num degrau todos disputam o mesmo pool; em dois, o de baixo só vê o que o
    de cima produziu. Achatar no digest daria a mesma versão para os dois, e
    dois resultados de benchmark alegariam ter medido a mesma coisa.
    """
    a = BlocoRegra(nome="L1", parametros={})
    b = BlocoRegra(nome="L2", parametros={})

    junto = _composicao(blocos=(a, b))
    separado = _composicao(
        etapas=(Etapa(nome="um", blocos=(a,)), Etapa(nome="dois", blocos=(b,)))
    )

    assert junto.version != separado.version


# --- o que as etapas destravam ---------------------------------------------


def test_o_ramo_deixa_de_ser_beco_sem_saida_quando_ha_degrau_depois():
    """A razão de existir desta fatia.

    Com uma etapa só, `condicao` produzindo `suspeito` era recusada — ninguém
    consumia o kind, e a única saída era declarar `entrega`. Com duas, o ramo
    tem um degrau de verdade depois dele, e a declaração não é mais necessária.
    """
    c = _composicao(
        etapas=(
            Etapa(nome="triagem", blocos=(_condicao("suspeito"),)),
            Etapa(nome="revisão", blocos=(_filtro("suspeito"),)),
        )
    )

    d = construir_composicao(c)

    assert [s.name for s in d.stages] == ["triagem", "revisão"]
    assert d.stages[0].produz == frozenset({"suspeito"})
    assert d.stages[1].consome == frozenset({"suspeito"})
    assert d.entrega == frozenset()


def test_um_ramo_que_NINGUEM_consome_continua_sendo_recusado():
    """A guarda não afrouxou porque agora há etapas: ela continua valendo, e a
    segunda etapa consumindo OUTRO kind não salva a primeira."""
    c = _composicao(
        etapas=(
            Etapa(nome="triagem", blocos=(_condicao("suspeito"),)),
            Etapa(nome="outra", blocos=(_filtro("coisa"),)),
        )
    )

    with pytest.raises(ValueError, match="beco sem saída"):
        construir_composicao(c)


def test_o_mesmo_bloco_em_DUAS_etapas_e_recusado():
    """Não por ambiguidade para o motor — por ambiguidade para as CONTAS.

    `Run.resolved_by_resolver` é indexado por nome, e dois resolvers homônimos
    fundiriam as contagens num número que não é de nenhum dos dois.
    """
    c = _composicao(
        etapas=(
            Etapa(nome="a", blocos=(_filtro("pedido"),)),
            Etapa(nome="b", blocos=(_filtro("pedido"),)),
        )
    )

    with pytest.raises(ValueError, match="repetido"):
        construir_composicao(c)


@dataclass(frozen=True)
class Pedido:
    valor: int


def test_duas_etapas_ROLDAM_de_verdade_e_o_item_atravessa():
    """A prova de ponta a ponta: o item entra como `pedido`, a etapa 1 o roteia
    para `suspeito`, e a etapa 2 — que só roda porque existe item desse kind —
    o consome."""
    c = _composicao(
        etapas=(
            Etapa(nome="triagem", blocos=(_condicao("suspeito"),)),
            Etapa(nome="revisão", blocos=(_filtro("suspeito"),)),
        )
    )
    d = construir_composicao(c)
    pool = WorkSet(
        items=(
            WorkItem(id="p1", kind="pedido", payload=Pedido(5000), origem="t"),
            WorkItem(id="p2", kind="pedido", payload=Pedido(10), origem="t"),
        )
    )

    run = execute(d, pool, model="claude-opus-5")

    # `p1` passou no teste: foi roteado e depois filtrado. `p2` não passou e
    # ficou — é a lacuna, contada, e ela nunca mente.
    resolvidos = {i for r in run.resolutions for i in r.item_ids}
    assert "p1" in resolvidos
    assert "p1+suspeito" in resolvidos
    assert [i.id for i in run.unresolved.items] == ["p2"]
