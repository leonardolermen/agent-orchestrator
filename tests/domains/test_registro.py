"""Os domínios declarados: a prova de que a plataforma deixou de ser um
conciliador.

O teste que carrega o peso é `test_os_TRES_dominios_se_declaram`: se ele voltar
a listar só conciliação, a plataforma voltou a ser um cardápio.
"""

import pytest

from orchestrator.agent.declarado import AgenteDeclarado, Dominio, construir_agente
from orchestrator.agent.llm import FakeLLMClient
from orchestrator.domains.registro import DOMINIOS, dominio


def test_os_TRES_dominios_se_declaram():
    """A pergunta do dono, virada em teste.

    Existiam seis resolvers escritos que o canvas não oferecia, porque a paleta
    era o `CATALOGO` do grill — o cardápio da conciliação.
    """
    assert set(DOMINIOS) == {"conciliacao", "swe", "procurement"}


def test_cada_dominio_tem_KIND_proprio_e_e_por_isso_que_nao_se_misturam():
    """`L1` trabalha `lancamento`, o triador trabalha `issue`. Uma cascata com
    os dois não é ruim — é vazia de sentido, porque o segundo roda sobre um
    pool que o primeiro nem enxerga."""
    kinds = [k for d in DOMINIOS.values() for k in d.kinds]

    assert len(kinds) == len(set(kinds)), "dois domínios disputando o mesmo kind"


def test_TODO_agente_declarado_CONSTROI():
    """"Validar é construir". `Dominio.__post_init__` já faz isso na importação;
    este teste existe para que a falha apareça com nome de teste e não como
    ImportError no meio de outra suíte."""
    for d in DOMINIOS.values():
        for a in d.agentes:
            agente = construir_agente(a, FakeLLMClient([]), d.ferramentas)
            assert agente.name == a.name


def test_nenhum_agente_confunde_ABSTENCAO_com_TIPO():
    """A invariante do P6.86 valendo para todos, não só para o `swe` onde ela
    foi descoberta — medindo, e depois de três execuções pagas."""
    for d in DOMINIOS.values():
        for a in d.agentes:
            assert a.abstem_com not in a.tipos, f"{d.id}/{a.name}"


def test_as_ferramentas_de_um_dominio_sao_CATALOGO_e_nao_registro_executavel():
    """Um registro ligado a um `ToolContext` vazio listaria igual e executaria
    devolvendo nada. `ligado` torna a diferença verificável."""
    conciliacao = dominio("conciliacao")

    assert conciliacao.ferramentas.names()
    assert not conciliacao.ferramentas.ligado


def test_dominio_SEM_ferramenta_declara_isso_em_vez_de_inventar():
    """`procurement` é esqueleto. Um registro vazio DIZ isso; inventar
    ferramentas para preencher a tela seria pior que a lacuna."""
    compras = dominio("procurement")

    assert compras.ferramentas.names() == ()
    # E `contexto=None` explícito: "não preciso de dados" é diferente de
    # "esqueci de ligar".
    assert compras.ferramentas.ligado


def test_o_agente_de_um_dominio_so_declara_ferramentas_DELE():
    for d in DOMINIOS.values():
        disponiveis = set(d.ferramentas.names())
        for a in d.agentes:
            assert set(a.ferramentas) <= disponiveis, f"{d.id}/{a.name}"


def test_dominio_desconhecido_lista_os_disponiveis():
    with pytest.raises(KeyError, match="disponíveis"):
        dominio("nao-existe")


def test_um_dominio_NOVO_nao_precisa_de_codigo_de_agente():
    """A prova da generalidade, do lado de fora.

    Declarar um domínio com um agente funcional é DADO: nenhuma função
    `units`, `parse` ou `abstain` é escrita. Se isto exigisse Python, o
    catálogo voltaria a ser um cardápio de coisas prontas.
    """
    novo = Dominio(
        id="suporte",
        nome="Triagem de chamados",
        kinds=("chamado",),
        agentes=(
            AgenteDeclarado(
                name="classificador",
                system="classifique o chamado",
                kind="chamado",
                prompt="{assunto}\n\n{descricao}",
                tipos=("INCIDENTE", "SOLICITACAO"),
                abstem_com="NAO_SEI",
            ),
        ),
    )

    agente = construir_agente(novo.agentes[0], FakeLLMClient([]))

    assert agente.name == "classificador"
