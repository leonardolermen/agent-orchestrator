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


# --- ida e volta pelo disco -------------------------------------------------


def test_o_disco_PRESERVA_as_etapas_e_a_entrega():
    """O defeito que quase passou: a composição era gravada só com os blocos
    achatados, e recarregá-la devolvia um workflow de UMA etapa, sem a
    declaração de saída. Silencioso e sobre estrutura — a pessoa montava dois
    degraus, salvava, e o que voltava era outro workflow com a mesma cara.
    """
    from orchestrator.authoring.composicao import de_json, para_json

    c = _composicao(
        etapas=(
            Etapa(nome="triagem", blocos=(_condicao("suspeito"),)),
            Etapa(nome="revisão", blocos=(_filtro("suspeito"),)),
        ),
        entrega=("relatorio",),
    )

    voltou = de_json(para_json(c))

    assert [e.nome for e in voltou.etapas] == ["triagem", "revisão"]
    assert voltou.entrega == ("relatorio",)
    # A VERSÃO sobrevive: ela é digerida do conteúdo, e um run antigo aponta
    # para a composição por ela.
    assert voltou.version == c.version


def test_arquivo_ANTIGO_sem_etapas_continua_carregando():
    """Os arquivos que já estão no disco têm só `blocos`, e são de uma etapa
    por construção — cair no açúcar reproduz exatamente o que significavam."""
    from orchestrator.authoring.composicao import de_json, para_json

    antigo = para_json(_composicao(blocos=(BlocoRegra(nome="L1", parametros={}),)))
    antigo["blocos"] = antigo.pop("etapas")[0]["blocos"]

    voltou = de_json(antigo)

    assert len(voltou.etapas) == 1
    assert voltou.nomes == ("L1",)


# --- Parallel e Merge: forma do grafo, não bloco ----------------------------


def _tabela() -> BlocoRegra:
    return BlocoRegra(
        nome="tabela",
        parametros={
            "kind": "pedido",
            "campo": "tipo",
            "de_para": ("PJ=empresa", "PF=pessoa"),
        },
    )


@dataclass(frozen=True)
class Cliente:
    tipo: str
    valor: int


def test_FAN_OUT_ja_existe_e_nao_precisa_de_bloco():
    """`Parallel` não é um bloco neste motor — é a FORMA do grafo.

    Um bloco que ramifica produz dois kinds; dois degraus depois dele consomem
    um cada, e ambos rodam porque `runtime/engine.py` devolve ao pool o que uma
    etapa não consome (`work.items + reservados`). Um "bloco Parallel" não teria
    o que fazer além de existir no desenho — que é a definição de decoração.
    """
    c = _composicao(
        etapas=(
            Etapa(nome="rotear", blocos=(_tabela(),)),
            Etapa(nome="PJ", blocos=(_filtro("empresa"),)),
            Etapa(
                nome="PF",
                blocos=(
                    BlocoRegra(
                        nome="validacao",
                        parametros={
                            "kind": "pessoa",
                            "campo": "valor",
                            # Propõe para quem FALHA: `valor=20` não é maior que
                            # 100, então o ramo PF vira proposta para o humano.
                            "teste": "maior",
                            "valor": "100",
                        },
                    ),
                ),
            ),
        )
    )
    d = construir_composicao(c)
    pool = WorkSet(
        items=(
            WorkItem(id="a", kind="pedido", payload=Cliente("PJ", 10), origem="t"),
            WorkItem(id="b", kind="pedido", payload=Cliente("PF", 20), origem="t"),
        )
    )

    run = execute(d, pool, model="claude-opus-5")

    # Os DOIS ramos rodaram: o de PJ resolveu o seu, o de PF propôs sobre o seu.
    resolvidos = {i for r in run.resolutions for i in r.item_ids}
    assert "a+empresa" in resolvidos
    assert [p.item_id for p in run.proposals] == ["b+pessoa"]


def test_MERGE_e_um_degrau_que_consome_os_DOIS_kinds():
    """`Merge` também não é bloco: é um degrau cujo `consome` tem os dois lados.

    Aqui `igualdade` casa um item vindo de cada ramo — os dois chegaram por
    caminhos diferentes e se encontram no degrau de baixo.
    """
    c = _composicao(
        etapas=(
            Etapa(nome="rotear", blocos=(_tabela(),)),
            Etapa(
                nome="juntar",
                blocos=(
                    BlocoRegra(
                        nome="igualdade",
                        parametros={
                            "esquerda": "empresa",
                            "direita": "pessoa",
                            "campos": ("valor",),
                        },
                    ),
                ),
            ),
        )
    )

    d = construir_composicao(c)

    assert d.stages[1].consome == frozenset({"empresa", "pessoa"})

    pool = WorkSet(
        items=(
            WorkItem(id="a", kind="pedido", payload=Cliente("PJ", 99), origem="t"),
            WorkItem(id="b", kind="pedido", payload=Cliente("PF", 99), origem="t"),
        )
    )
    run = execute(d, pool, model="claude-opus-5")

    juntou = [r for r in run.resolutions if r.produced_by == "igualdade"]
    assert len(juntou) == 1
    assert juntou[0].item_ids == frozenset({"a+empresa", "b+pessoa"})


# --- Loop: max_rondas, que é propriedade do workflow e não degrau -----------


def test_as_rondas_chegam_a_definicao():
    c = _composicao(blocos=(BlocoRegra(nome="L1", parametros={}),), max_rondas=3)

    assert construir_composicao(c).max_rondas == 3


def test_zero_rondas_e_recusado_na_COMPOSICAO():
    """A recusa mora no kernel também; aqui ela chega antes. Quem compõe na tela
    merece a recusa na composição, não na execução."""
    with pytest.raises(ValueError, match="max_rondas"):
        _composicao(blocos=(BlocoRegra(nome="L1", parametros={}),), max_rondas=0)


def test_as_rondas_mudam_a_VERSAO():
    # Um workflow que pode rodar três vezes não é o mesmo que roda uma: o
    # segundo não tem aresta de volta.
    b = (BlocoRegra(nome="L1", parametros={}),)

    assert _composicao(blocos=b).version != _composicao(blocos=b, max_rondas=2).version


def test_o_disco_preserva_as_rondas():
    from orchestrator.authoring.composicao import de_json, para_json

    c = _composicao(blocos=(BlocoRegra(nome="L1", parametros={}),), max_rondas=4)

    assert de_json(para_json(c)).max_rondas == 4
