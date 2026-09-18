"""Os três destinos de um item, e a diferença entre eles.

Filtro RESOLVE, validação PROPÕE, condição ROTEIA. São três verbos, e o teste
que carrega o peso deste arquivo é `test_os_tres_destinos_sao_distintos`: se
dois deles passarem a fazer a mesma coisa com o pool, a paleta tem um bloco a
mais e ninguém percebe.
"""

from dataclasses import dataclass

import pytest

from orchestrator.kernel.resolution import Confidence
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras import Condicao, Filtro, Validacao
from orchestrator.regras.predicado import ComparacaoImpossivel


@dataclass(frozen=True)
class Pedido:
    valor: int
    assunto: str = ""


def _pool(*valores: int) -> WorkSet:
    return WorkSet(
        items=tuple(
            WorkItem(id=f"p{i}", kind="pedido", payload=Pedido(v), origem="teste")
            for i, v in enumerate(valores)
        )
    )


# --- filtro: o item SAI do pool --------------------------------------------


def test_filtro_resolve_quem_passa_no_teste():
    saida = Filtro(kind="pedido", campo="valor", teste="menor", valor="100").resolve(
        _pool(50, 500)
    )

    assert [sorted(r.item_ids) for r in saida.resolutions] == [["p0"]]
    assert saida.proposals == []
    assert saida.produced == ()


def test_o_descarte_do_filtro_NAO_e_mudo():
    """Resolver sem produzir faz o item sumir do run, e `agent/tarefa.py` trata
    isso como erro alto. Aqui sumir é o pedido — o que não pode é sumir sem
    dizer por quê, porque a pergunta "por que este item não chegou ao agente?"
    precisa ter resposta no trace."""
    saida = Filtro(
        kind="pedido", campo="valor", teste="menor", valor="100", motivo="abaixo do piso"
    ).resolve(_pool(50))

    assert "abaixo do piso" in saida.resolutions[0].rule
    assert "valor menor 100" in saida.resolutions[0].rule


# --- validação: o item FICA, com uma proposta ------------------------------


def test_validacao_propoe_para_quem_FALHA_a_exigencia():
    # A inversão é deliberada: escreve-se a exigência, não a violação.
    saida = Validacao(
        kind="pedido", campo="valor", teste="menor_ou_igual", valor="10000"
    ).resolve(_pool(500, 50000))

    assert saida.resolutions == []
    assert [p.item_id for p in saida.proposals] == ["p1"]


def test_a_proposta_de_uma_REGRA_tem_confianca_ALTA():
    """Um agente diz "acho que"; esta regra CONFERIU. E confiança alta exige
    evidência — que aqui é o campo e o valor que reprovaram."""
    saida = Validacao(
        kind="pedido", campo="valor", teste="menor_ou_igual", valor="10000"
    ).resolve(_pool(50000))

    p = saida.proposals[0]
    assert p.confianca is Confidence.ALTA
    assert "valor=50000" in p.evidencia


def test_validacao_nao_encolhe_o_pool():
    """A invariante que o `ResolverOutput` torna estrutural: `proposals` não
    aparece em `without()` nem em `com()`. Proposta explica; quem resolve é o
    humano."""
    saida = Validacao(
        kind="pedido", campo="valor", teste="menor_ou_igual", valor="10"
    ).resolve(_pool(50000))

    assert saida.resolutions == []
    assert saida.produced == ()


# --- condição: o item MUDA DE RAMO -----------------------------------------


def test_condicao_consome_e_produz_em_conjuncao():
    """A §3.1, que `agent/tarefa.py` já impõe: transformar é consumir A **e**
    produzir B. Produzir sem consumir deixaria o mesmo dado em dois lugares;
    consumir sem produzir faria o item sumir."""
    saida = Condicao(
        kind="pedido", campo="valor", teste="maior", valor="10000", produz="suspeito"
    ).resolve(_pool(500, 50000))

    assert [sorted(r.item_ids) for r in saida.resolutions] == [["p1"]]
    assert [(i.id, i.kind) for i in saida.produced] == [("p1+suspeito", "suspeito")]


def test_o_payload_atravessa_intacto():
    # Rotear é mudar de caminho, não mudar o dado. Quem enriquece é outro bloco.
    original = Pedido(50000, "urgente")
    work = WorkSet(
        items=(WorkItem(id="p0", kind="pedido", payload=original, origem="t"),)
    )

    saida = Condicao(
        kind="pedido", campo="valor", teste="maior", valor="1", produz="suspeito"
    ).resolve(work)

    assert saida.produced[0].payload is original


def test_o_id_produzido_NAO_colide_com_o_consumido():
    # `WorkSet` recusa id repetido. Sem o sufixo, a guarda certa falharia pelo
    # motivo errado, no meio de uma execução.
    saida = Condicao(
        kind="pedido", campo="valor", teste="maior", valor="1", produz="suspeito"
    ).resolve(_pool(50000))

    assert saida.produced[0].id != next(iter(saida.resolutions[0].item_ids))


def test_condicao_sem_ramo_e_recusada_na_construcao():
    with pytest.raises(ValueError, match="filtro"):
        Condicao(kind="pedido", campo="valor", teste="maior", valor="1")
    with pytest.raises(ValueError, match="a si mesmo"):
        Condicao(
            kind="pedido", campo="valor", teste="maior", valor="1", produz="pedido"
        )


# --- a diferença entre os três ---------------------------------------------


def test_os_tres_destinos_sao_distintos():
    """O teste que carrega o peso: cada bloco mexe no pool de um jeito só.

    Se dois deles convergirem, a paleta passa a ter um bloco a mais que não
    significa nada — e quem monta o workflow escolhe entre dois nomes para o
    mesmo comportamento.
    """
    work = _pool(50000)
    args = dict(kind="pedido", campo="valor", teste="maior", valor="1")

    filtro = Filtro(**args).resolve(work)
    validacao = Validacao(
        kind="pedido", campo="valor", teste="menor", valor="1"
    ).resolve(work)
    condicao = Condicao(**args, produz="suspeito").resolve(work)

    # (encolhe?, propõe?, cresce?)
    forma = lambda s: (bool(s.resolutions), bool(s.proposals), bool(s.produced))  # noqa: E731

    assert forma(filtro) == (True, False, False)
    assert forma(validacao) == (False, True, False)
    assert forma(condicao) == (True, False, True)


# --- o predicado, que os três compartilham ---------------------------------


def test_o_mesmo_bloco_serve_a_limiar_e_a_padrao():
    """"Limiar" e "padrão" não são dois blocos: são o mesmo bloco com um teste
    diferente. Sem isto, o catálogo teria o produto cartesiano de destino por
    tipo de teste."""
    work = WorkSet(
        items=(
            WorkItem(id="a", kind="pedido", payload=Pedido(5, "fatura 12"), origem="t"),
            WorkItem(id="b", kind="pedido", payload=Pedido(900, "boleto"), origem="t"),
        )
    )

    por_limiar = Filtro(kind="pedido", campo="valor", teste="maior", valor="100")
    por_padrao = Filtro(kind="pedido", campo="assunto", teste="contem", valor="fatura")

    assert [sorted(r.item_ids) for r in por_limiar.resolve(work).resolutions] == [["b"]]
    assert [sorted(r.item_ids) for r in por_padrao.resolve(work).resolutions] == [["a"]]


def test_comparar_grandeza_com_texto_LEVANTA_em_vez_de_dizer_nao():
    """Responder `False` trataria "não sei" como "não", e o bloco filtraria
    zero itens parecendo que não havia o que filtrar."""
    work = WorkSet(
        items=(WorkItem(id="a", kind="pedido", payload=Pedido(1, "abc"), origem="t"),)
    )

    with pytest.raises(ComparacaoImpossivel, match="grandeza"):
        Filtro(kind="pedido", campo="assunto", teste="maior", valor="10").resolve(work)


def test_teste_desconhecido_e_recusado_na_construcao():
    with pytest.raises(ValueError):
        Filtro(kind="pedido", campo="valor", teste="mais_ou_menos", valor="1")


def test_campo_vazio_nao_passa_em_teste_de_comparacao():
    # `None > 10` é erro em Python; responder `False` é o certo aqui, e quem
    # quer perguntar por ausência usa `vazio`.
    @dataclass(frozen=True)
    class Talvez:
        valor: int | None

    work = WorkSet(
        items=(WorkItem(id="a", kind="pedido", payload=Talvez(None), origem="t"),)
    )

    assert Filtro(kind="pedido", campo="valor", teste="maior", valor="1").resolve(
        work
    ).resolutions == []
    assert len(
        Filtro(kind="pedido", campo="valor", teste="vazio").resolve(work).resolutions
    ) == 1


# --- a fiação do ramo, derivada para quem compõe ---------------------------


def test_a_condicao_DECLARA_o_kind_do_ramo():
    """Sem isto, a composição passava e a EXECUÇÃO recusava.

    `ResolverDescription` declarava `consome` e não `produz`, então
    `authoring/composicao.py` derivava metade da fiação e deixava a outra no
    default — com o comentário "nenhum bloco do catálogo produz item", que era
    verdade até este bloco existir. O motor então recusava com "produziu kind
    não declarado": um erro de execução sobre uma escolha que a tela tinha
    acabado de aceitar.
    """
    d = Condicao(
        kind="pedido", campo="valor", teste="maior", valor="1", produz="suspeito"
    ).describe()

    assert d.consome == frozenset({"pedido"})
    assert d.produz == frozenset({"suspeito"})


def test_compor_um_ramo_SEM_destino_recusa_na_COMPOSICAO():
    """E recusa com a mensagem certa: beco sem saída.

    É o comportamento desejado, não uma limitação escondida. Um item roteado
    para um kind que ninguém consome ficaria no pool para sempre. Quem monta
    precisa dar um destino ao ramo — outro degrau que o consuma, ou uma
    declaração de que aquele kind É a saída do run (`entrega`).

    A recusa acontecer aqui, e não ao rodar, é o que este arquivo comprou.
    """
    from datetime import UTC, datetime

    from orchestrator.authoring.composicao import (
        BlocoRegra,
        Composicao,
        construir_composicao,
    )

    c = Composicao(
        id="t",
        nome="t",
        blocos=(
            BlocoRegra(
                nome="condicao",
                parametros={
                    "kind": "banco",
                    "campo": "amount",
                    "teste": "maior",
                    "valor": "0",
                    "produz": "suspeito",
                },
            ),
        ),
        gerado_em=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="beco sem saída"):
        construir_composicao(c)
