"""A composição: uma cascata do catálogo, com agente declarado inline.

O que a `Receita` do grill não sabia carregar é o `BlocoAgente`: um agente que
não existe pronto em catálogo nenhum, criado na própria composição. Tentar
encaixá-lo em `ResolverReceita(nome, parametros: dict[str, int])` produziria um
`int` no tipo carregando um prompt — e é esse `int` que avisa que não cabe.
"""

from datetime import UTC, datetime

import pytest

from orchestrator.agent.declarado import AgenteDeclarado
from orchestrator.agent.llm import FakeLLMClient
from orchestrator.authoring.composicao import (
    BlocoAgente,
    BlocoRegra,
    Composicao,
    construir_composicao,
    de_json,
    gravar,
    ler,
    listar,
    para_json,
)
from orchestrator.conciliacao.ferramentas import ToolContext

AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _agente(**kw) -> AgenteDeclarado:
    base = dict(
        name="meu-triador",
        system="classifique",
        kind="issue",
        prompt="{titulo}\n\n{corpo}",
        tipos=("BUG", "FEATURE"),
        abstem_com="NAO_SEI",
    )
    return AgenteDeclarado(**{**base, **kw})


def _comp(blocos, cid="minha") -> Composicao:
    return Composicao(id=cid, nome="Minha", gerado_em=AGORA, blocos=tuple(blocos))


def _construir(c, contexto=None):
    return construir_composicao(c, cliente=FakeLLMClient([]), contexto=contexto)


# -- o que a Receita não sabia carregar ------------------------------------


def test_agente_declarado_INLINE_vira_resolver():
    d = _construir(_comp([BlocoAgente(declaracao=_agente())]))

    (r,) = d.stages[0].cascade
    assert r.name == "meu-triador"


def test_o_agente_inline_recebe_as_ferramentas_do_CATALOGO():
    d = _construir(
        _comp([BlocoAgente(declaracao=_agente(ferramentas=("contar_palavras",)))])
    )

    (r,) = d.stages[0].cascade
    assert r.tools.names() == ("contar_palavras",)


def test_ferramenta_INEXISTENTE_e_recusada():
    """O recorte é sobre o catálogo INTEIRO — não existe mais uma partição de
    ferramentas por domínio. O que continua sendo recusado é declarar uma
    ferramenta que ninguém publicou."""
    with pytest.raises(ValueError, match="ferramenta inexistente"):
        _construir(
            _comp([BlocoAgente(declaracao=_agente(ferramentas=("nao_existe",)))])
        )


def test_bloco_desconhecido_no_catalogo_LISTA_os_disponiveis():
    """A mensagem é lida por quem compõe — e pelo modelo, que se corrige com
    ela. Um "não achei" sem a lista obriga a adivinhar o nome certo."""
    with pytest.raises(ValueError, match="bloco desconhecido no catálogo"):
        _construir(_comp([BlocoRegra(nome="nao-existe")]))


def test_o_degrau_HUMANO_do_catalogo_COMPOE():
    """O bloco que a paleta oferecia e a composição não conseguia construir.

    `revisor` é a única regra de classe `HUMANO` do catálogo, e ele depende da
    FILA de decisões — que não cabe na assinatura uniforme
    `(parametros) -> Resolver`. Sem o ramo por `cost_class`,
    `regra.construir({})` caía em `_revisor_precisa_da_fila` e "Compor e
    validar" devolvia 422 com um texto escrito para quem implementa. O degrau
    humano é o que FECHA a cascata, e é a razão declarada de o `revisor` ter
    sido carregado para o catálogo plano: sem ele, a composição — o caminho
    que esta fatia existe para abrir — era o único que não fechava.
    """
    c = _comp([BlocoRegra(nome="L1"), BlocoRegra(nome="revisor")])

    cascata = _construir(c).stages[0].ordered()

    assert [r.name for r in cascata] == ["L1", "revisor"]
    assert [r.cost_class.name for r in cascata] == ["REGRA", "HUMANO"]


def test_o_revisor_composto_LE_A_FILA_QUE_RECEBEU():
    """O ramo HUMANO existe para a fila REAL chegar — não para o bloco parar
    de levantar.

    Um `RevisorHumano(fila=Fila.vazia())` cravado aqui construiria igual e
    passaria o teste acima, enquanto nenhuma decisão aprovada chegaria à
    execução: o fallback silencioso que `_revisor_precisa_da_fila` existe para
    impedir. Este teste é o que torna a diferença visível — a fila que entra
    por palavra-chave é a que o resolver carrega.
    """
    from orchestrator.review.fila import Fila

    minha = Fila.vazia()

    d = construir_composicao(_comp([BlocoRegra(nome="revisor")]), fila=minha)

    (r,) = d.stages[0].cascade
    assert r.fila is minha


# -- a ordem não é do autor -------------------------------------------------


def test_a_ordem_dos_BLOCOS_nao_decide_a_ordem_da_CASCATA():
    """A mesma defesa contra decoração que o canvas tem, agora no formato
    persistido: não existe campo de ordem, e `Stage.ordered()` manda."""
    c = _comp(
        [
            BlocoAgente(declaracao=_agente(kind="requisicao", name="buscador-meu")),
            BlocoRegra(nome="preferido"),
        ]
    )

    classes = [r.cost_class.name for r in _construir(c).stages[0].ordered()]

    assert classes == ["REGRA", "AGENTE"]


# -- validar construindo ----------------------------------------------------


def test_bloco_REPETIDO_e_recusado():
    """O segundo rodaria sobre o pool que o primeiro já esvaziou."""
    c = _comp([BlocoRegra(nome="preferido"), BlocoRegra(nome="preferido")])

    with pytest.raises(ValueError, match="esvaziou"):
        _construir(c)


def test_parametro_desconhecido_de_REGRA_e_recusado():
    c = _comp([BlocoRegra(nome="L2", parametros={"nao_existe": 3})])

    with pytest.raises(ValueError, match="parâmetro desconhecido"):
        _construir(c, contexto=ToolContext([], []))


def test_composicao_VAZIA_e_recusada():
    with pytest.raises(ValueError, match="pelo menos um bloco"):
        _comp([])


def test_gerado_em_sem_fuso_e_recusado():
    with pytest.raises(ValueError, match="fuso"):
        Composicao(
            id="x",
            nome="X",
            gerado_em=datetime(2026, 9, 16, 12, 0),
            blocos=(BlocoAgente(declaracao=_agente()),),
        )


# -- a versão ---------------------------------------------------------------


def test_a_versao_e_derivada_do_CONTEUDO():
    """Dois resultados de benchmark só são comparáveis se mediram a mesma
    cascata. Sem derivação, nada impede duas composições alegarem a mesma."""
    a = _comp([BlocoAgente(declaracao=_agente())])
    b = _comp([BlocoAgente(declaracao=_agente())])

    assert a.version == b.version


def test_mudar_o_PROMPT_muda_a_versao():
    a = _comp([BlocoAgente(declaracao=_agente(prompt="{titulo}"))])
    b = _comp([BlocoAgente(declaracao=_agente(prompt="{titulo} {corpo}"))])

    assert a.version != b.version


def test_mudar_um_PARAMETRO_de_regra_muda_a_versao():
    a = _comp([BlocoRegra(nome="L2", parametros={"max_cents": 5})])
    b = _comp([BlocoRegra(nome="L2", parametros={"max_cents": 50})])

    assert a.version != b.version


# -- serialização e disco ---------------------------------------------------


def test_o_roundtrip_preserva_TUDO_inclusive_o_agente_inline():
    c = _comp(
        [
            BlocoRegra(nome="preferido"),
            BlocoAgente(
                declaracao=_agente(kind="requisicao", name="b", max_turns=9)
            ),
        ]
    )

    voltou = de_json(para_json(c))

    assert voltou.version == c.version
    assert voltou.blocos[1].declaracao.max_turns == 9


def test_o_que_vai_para_o_DISCO_nao_carrega_dominio():
    """A outra metade da remoção, no formato persistido.

    `Composicao.dominio` sumiu do dataclass, mas um `para_json` que continuasse
    escrevendo a chave (ou um `de_json` que continuasse a exigir) manteria o
    conceito vivo no disco, onde nenhum type checker olha. E um campo gravado
    que ninguém lê é o próximo a ser lido por engano.
    """
    d = para_json(_comp([BlocoAgente(declaracao=_agente())]))

    assert "dominio" not in d
    assert de_json(d).version == _comp([BlocoAgente(declaracao=_agente())]).version


def test_tipo_de_bloco_desconhecido_LEVANTA_em_vez_de_sumir():
    """Um tipo novo precisa de uma decisão sobre o que ele significa na
    cascata, não de um `else` que o ignora em silêncio."""
    d = para_json(_comp([BlocoAgente(declaracao=_agente())]))
    d["blocos"][0]["tipo"] = "futuro"

    with pytest.raises(ValueError, match="tipo de bloco desconhecido"):
        de_json(d)


def test_gravar_RECUSA_sobrescrever(tmp_path):
    """Runs antigos apontam para a composição pela versão; trocar o conteúdo
    sob o mesmo id faria um run apontar para uma cascata que nunca rodou."""
    c = _comp([BlocoAgente(declaracao=_agente())])
    gravar(c, tmp_path)

    with pytest.raises(FileExistsError, match="já existe"):
        gravar(c, tmp_path)


def test_o_que_gravou_LE_igual(tmp_path):
    c = _comp([BlocoAgente(declaracao=_agente())])
    gravar(c, tmp_path)

    assert ler("minha", tmp_path).version == c.version


def test_arquivo_ILEGIVEL_nao_derruba_a_listagem(tmp_path, capsys):
    """Mesma política de `descrever` em `workflows.py`: um arquivo ruim não
    derruba a listagem inteira, mas também não some em silêncio."""
    gravar(_comp([BlocoAgente(declaracao=_agente())], cid="boa"), tmp_path)
    (tmp_path / "ruim.json").write_text('{"id": "ruim"}', encoding="utf-8")

    listadas = listar(tmp_path)

    assert [c.id for c in listadas] == ["boa"]
    assert "ilegível" in capsys.readouterr().err


# -- compor não é executar --------------------------------------------------


def test_compor_SEM_contexto_deixa_o_registro_como_CATALOGO():
    """A diferença entre compor e executar, verificável.

    `com_contexto(None)` ligaria o registro a nada, e a primeira chamada de
    ferramenta estouraria em `None.bank`. Um catálogo recusa com texto.
    """
    d = _construir(
        _comp(
            [BlocoAgente(declaracao=_agente(kind="lancamento", name="meu-investigador",
                                            ferramentas=("buscar_lancamentos",)))]
        )
    )

    (r,) = d.stages[0].cascade
    assert not r.tools.ligado
    assert "não ligado" in (r.tools.call("buscar_lancamentos", {}).error or "")


def test_compor_COM_contexto_entrega_um_agente_que_EXECUTA():
    """O outro lado. Era o defeito: `construir_agente` recortava as ferramentas
    com um `ToolRegistry` novo e perdia o contexto, então NENHUM agente composto
    conseguia usar ferramenta — em silêncio, dentro de um laço pago."""
    d = _construir(
        _comp(
            [BlocoAgente(declaracao=_agente(kind="lancamento", name="meu-investigador",
                                            ferramentas=("buscar_lancamentos",)))]
        ),
        contexto=ToolContext([], []),
    )

    (r,) = d.stages[0].cascade
    assert r.tools.ligado
    assert r.tools.call("buscar_lancamentos", {"documento": "x"}).error is None


def test_o_cliente_default_e_a_TRANCA_e_nao_um_modelo():
    """`construir_composicao` sem cliente valida e recusa executar — mesma
    escolha do `ClienteAusente` em `grill.receita.construir`."""
    from orchestrator.authoring.composicao import construir_composicao

    d = construir_composicao(_comp([BlocoAgente(declaracao=_agente())]))

    (r,) = d.stages[0].cascade
    with pytest.raises(RuntimeError, match="não fala com modelo"):
        r.client.complete("", [], [])
