"""A fiação derivada: `consome_de` e os três construtores que a usam.

Uma função, três chamadas explícitas — e não uma derivação dentro de
`Stage.__post_init__`. Popular `consome` no kernel trocaria em silêncio o
significado do default vazio ("vê o pool inteiro") para toda definição escrita
em Python. Aqui cada construtor decide, e o kernel não muda de semântica.
"""

from datetime import UTC, datetime

from orchestrator.agent.declarado import AgenteDeclarado
from orchestrator.authoring.composicao import (
    BlocoAgente,
    BlocoRegra,
    Composicao,
    construir_composicao,
)
from orchestrator.conciliacao import default_definition
from orchestrator.domains.registro import CATALOGO
from orchestrator.grill.receita import Receita, ResolverReceita, construir
from orchestrator.kernel.definition import consome_de


def _regra(nome):
    return next(r for r in CATALOGO.regras if r.nome == nome).construir({})


def test_consome_de_e_a_UNIAO_do_que_cada_resolver_declara():
    assert consome_de([_regra("L1"), _regra("preferido")]) == frozenset(
        {"banco", "contabil", "requisicao", "fornecedor"}
    )


def test_consome_de_cascata_vazia_e_vazio_e_nao_levanta():
    assert consome_de([]) == frozenset()


def test_a_conciliacao_EMBUTIDA_consome_banco_e_contabil():
    (stage,) = default_definition().stages
    assert stage.consome == frozenset({"banco", "contabil"})


def test_uma_RECEITA_consome_a_uniao_dos_blocos():
    receita = Receita(
        id="r", nome="r", justificativa="", gerado_em=datetime.now(UTC),
        resolvers=(ResolverReceita(nome="L1", parametros={}),),
    )
    (stage,) = construir(receita).stages
    assert stage.consome == frozenset({"banco", "contabil"})


def test_uma_COMPOSICAO_consome_os_kinds_dos_blocos_inclusive_do_agente():
    """A ponta que o cabeçalho de `authoring/composicao.py` chamava de X7:
    `construir_composicao` passa a POPULAR `consome` a partir dos blocos."""
    decl = AgenteDeclarado(
        name="meu-triador", system="classifique", kind="issue",
        prompt="{titulo}", tipos=("BUG",), abstem_com="NAO_SEI",
    )
    c = Composicao(
        id="c", nome="c", gerado_em=datetime.now(UTC),
        blocos=(BlocoRegra(nome="L1", parametros={}), BlocoAgente(declaracao=decl)),
    )
    (stage,) = construir_composicao(c).stages
    assert stage.consome == frozenset({"banco", "contabil", "issue"})
