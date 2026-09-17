"""A composição: uma cascata de qualquer domínio, com agente declarado inline.

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


def _comp(blocos, dominio="swe", cid="minha") -> Composicao:
    return Composicao(
        id=cid, nome="Minha", dominio=dominio, gerado_em=AGORA, blocos=tuple(blocos)
    )


def _construir(c, contexto=None):
    return construir_composicao(c, cliente=FakeLLMClient([]), contexto=contexto)


# -- o que a Receita não sabia carregar ------------------------------------


def test_agente_declarado_INLINE_vira_resolver():
    d = _construir(_comp([BlocoAgente(declaracao=_agente())]))

    (r,) = d.stages[0].cascade
    assert r.name == "meu-triador"


def test_o_agente_inline_recebe_as_ferramentas_do_DOMINIO():
    d = _construir(
        _comp([BlocoAgente(declaracao=_agente(ferramentas=("contar_palavras",)))])
    )

    (r,) = d.stages[0].cascade
    assert r.tools.names() == ("contar_palavras",)


def test_ferramenta_de_OUTRO_dominio_e_recusada():
    with pytest.raises(ValueError, match="ferramenta inexistente"):
        _construir(
            _comp([BlocoAgente(declaracao=_agente(ferramentas=("buscar_lancamentos",)))])
        )


# -- um domínio só ----------------------------------------------------------


def test_agente_de_KIND_ESTRANHO_ao_dominio_e_recusado():
    """Ele rodaria sobre um pool que não enxerga."""
    with pytest.raises(ValueError, match="não é do domínio"):
        _construir(_comp([BlocoAgente(declaracao=_agente(kind="lancamento"))]))


def test_regra_de_OUTRO_dominio_e_recusada():
    with pytest.raises(ValueError, match="regra desconhecida"):
        _construir(_comp([BlocoRegra(nome="L1")], dominio="swe"))


# -- a ordem não é do autor -------------------------------------------------


def test_a_ordem_dos_BLOCOS_nao_decide_a_ordem_da_CASCATA():
    """A mesma defesa contra decoração que o canvas tem, agora no formato
    persistido: não existe campo de ordem, e `Stage.ordered()` manda."""
    c = _comp(
        [
            BlocoAgente(declaracao=_agente(kind="requisicao", name="buscador-meu")),
            BlocoRegra(nome="preferido"),
        ],
        dominio="procurement",
    )

    classes = [r.cost_class.name for r in _construir(c).stages[0].ordered()]

    assert classes == ["REGRA", "AGENTE"]


# -- validar construindo ----------------------------------------------------


def test_bloco_REPETIDO_e_recusado():
    """O segundo rodaria sobre o pool que o primeiro já esvaziou."""
    c = _comp([BlocoRegra(nome="preferido"), BlocoRegra(nome="preferido")], "procurement")

    with pytest.raises(ValueError, match="esvaziou"):
        _construir(c)


def test_parametro_desconhecido_de_REGRA_e_recusado():
    c = _comp([BlocoRegra(nome="L2", parametros={"nao_existe": 3})], "conciliacao")

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
            dominio="swe",
            gerado_em=datetime(2026, 9, 16, 12, 0),
            blocos=(BlocoAgente(declaracao=_agente()),),
        )


def test_dominio_desconhecido_lista_os_disponiveis():
    with pytest.raises(KeyError, match="disponíveis"):
        _construir(_comp([BlocoRegra(nome="x")], dominio="nao-existe"))


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
    a = _comp([BlocoRegra(nome="L2", parametros={"max_cents": 5})], "conciliacao")
    b = _comp([BlocoRegra(nome="L2", parametros={"max_cents": 50})], "conciliacao")

    assert a.version != b.version


# -- serialização e disco ---------------------------------------------------


def test_o_roundtrip_preserva_TUDO_inclusive_o_agente_inline():
    c = _comp(
        [
            BlocoRegra(nome="preferido"),
            BlocoAgente(
                declaracao=_agente(kind="requisicao", name="b", max_turns=9)
            ),
        ],
        "procurement",
    )

    voltou = de_json(para_json(c))

    assert voltou.version == c.version
    assert voltou.blocos[1].declaracao.max_turns == 9


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
