"""O bloco que transforma, no formato que a tela grava."""

from orchestrator.agent.declarado import TarefaDeclarada
from orchestrator.authoring.composicao import (
    BlocoTarefa,
    Composicao,
    Etapa,
    agora,
    construir_composicao,
    de_json,
    para_json,
)


def _tarefa(nome="escritor", kind="issue", produz="rascunho") -> BlocoTarefa:
    return BlocoTarefa(
        declaracao=TarefaDeclarada(
            name=nome,
            system="escreva",
            kind=kind,
            produz=produz,
            prompt="{titulo}" if kind == "issue" else "{" + kind + "}",
        )
    )


def _composicao(*blocos, entrega=("texto_final",), etapas=None) -> Composicao:
    return Composicao(
        id="c1",
        nome="cadeia",
        gerado_em=agora(),
        etapas=etapas or (Etapa(nome="escrever", blocos=blocos),),
        entrega=entrega,
    )


def test_uma_cascata_com_bloco_TAREFA_constroi():
    definicao = construir_composicao(_composicao(_tarefa(), entrega=("rascunho",)))

    (stage,) = definicao.stages
    (resolver,) = stage.cascade
    assert resolver.name == "escritor"


def test_o_degrau_DERIVA_consome_e_produz_do_bloco():
    """Sem `describe()` publicando os dois, o stage sairia com conjuntos vazios
    e a execução recusaria o kind produzido."""
    definicao = construir_composicao(_composicao(_tarefa(), entrega=("rascunho",)))

    (stage,) = definicao.stages
    assert stage.consome == frozenset({"issue"})
    assert stage.produz == frozenset({"rascunho"})


def test_duas_etapas_ENCADEIAM_pelo_kind():
    """A cadeia que o produto não sabia montar: o revisor consome o que o
    escritor produz."""
    c = _composicao(
        etapas=(
            Etapa(nome="escrever", blocos=(_tarefa(),)),
            Etapa(
                nome="revisar",
                blocos=(_tarefa("revisor", kind="rascunho", produz="texto_final"),),
            ),
        )
    )

    definicao = construir_composicao(c)

    primeiro, segundo = definicao.stages
    assert primeiro.produz == frozenset({"rascunho"})
    assert segundo.consome == frozenset({"rascunho"})


def test_o_bloco_tarefa_SOBREVIVE_ao_disco():
    c = _composicao(_tarefa(), entrega=("rascunho",))

    voltou = de_json(para_json(c))

    assert voltou.blocos == c.blocos
    # A versão é derivada do conteúdo: dois workflows diferentes não podem
    # alegar a mesma, senão dois resultados de benchmark passam a dizer que
    # mediram a mesma cascata.
    assert voltou.version == c.version


def test_compor_uma_cascata_de_TAREFA_nao_gasta_nada():
    """Compor é grátis: o cliente default é `ClienteDeValidacao`, a tranca que
    constrói o resolver e recusa falar com modelo."""
    from orchestrator.kernel.cost import CostClass

    definicao = construir_composicao(_composicao(_tarefa(), entrega=("rascunho",)))

    (stage,) = definicao.stages
    assert stage.cascade[0].cost_class is CostClass.AGENTE
