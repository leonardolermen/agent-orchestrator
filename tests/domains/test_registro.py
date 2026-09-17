"""Os domínios declarados: a prova de que a plataforma deixou de ser um
conciliador.

O teste que carrega o peso é `test_os_TRES_dominios_se_declaram`: se ele voltar
a listar só conciliação, a plataforma voltou a ser um cardápio.
"""

import pytest

from orchestrator.agent.declarado import AgenteDeclarado, Dominio, construir_agente
from orchestrator.agent.llm import FakeLLMClient
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.domains.registro import CATALOGO, DOMINIOS, Catalogo, dominio
from orchestrator.kernel.cost import CostClass


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


def test_o_catalogo_e_PLANO_e_traz_tudo_junto():
    """Um catálogo só, sem agrupamento. É o quadro em branco do §0.1.

    As contagens vêm das três origens somadas: 3 regras de conciliação + 2 de
    compras + o `revisor`, e 1 agente de cada domínio.
    """
    nomes_de_regra = {r.nome for r in CATALOGO.regras}

    assert {"L1", "L2", "L3", "preferido", "anteriores"} <= nomes_de_regra
    assert {a.name for a in CATALOGO.agentes} == {"investigador", "triador", "buscador"}


def test_o_catalogo_carrega_o_degrau_HUMANO():
    """O `revisor` existia só no catálogo do grill e em `Dominio` nenhum.

    Fundir os dois sem ele perderia o degrau que FECHA a cascata — e a
    invariante "proposta não resolve" depende de existir alguém que resolva.
    """
    revisor = next(r for r in CATALOGO.regras if r.nome == "revisor")

    assert revisor.cost_class is CostClass.HUMANO


def test_as_ferramentas_dos_TRES_dominios_estao_no_MESMO_registro():
    """"Todas as nossas tools disponíveis pra ele" — o pedido, virado teste."""
    nomes = CATALOGO.ferramentas.names()

    assert "contar_palavras" in nomes  # veio do swe
    assert len(nomes) >= 6  # as 5 da conciliação mais a do swe


def test_o_catalogo_RECUSA_bloco_com_nome_repetido():
    """A guarda que migrou de `Dominio.__post_init__`, e que fica MAIS
    perigosa aqui.

    Antes a colisão só podia acontecer dentro de um domínio; num catálogo
    plano ela pode acontecer entre quaisquer dois blocos do sistema. A
    composição indexa bloco por nome, e dois iguais fariam a cascata depender
    de quem foi procurado primeiro.
    """
    from orchestrator.agent.declarado import AgenteDeclarado, RegraDisponivel

    regra = RegraDisponivel(
        nome="colide", cost_class=CostClass.REGRA, resumo="x",
        construir=lambda p: None,
    )
    agente = AgenteDeclarado(
        name="colide", system="s", kind="k", prompt="{x}",
        tipos=("A",), abstem_com="NAO_SEI",
    )

    with pytest.raises(ValueError, match="nome repetido"):
        Catalogo(
            ferramentas=ToolRegistry([], contexto=None),
            regras=(regra,),
            agentes=(agente,),
        )


def test_o_catalogo_VALIDA_CONSTRUINDO_cada_agente():
    """"Validar é construir" — a outra guarda que migrou.

    Sem ela, uma declaração inválida só falharia ao EXECUTAR, que é depois de
    a pessoa ter montado a cascata inteira e clicado em rodar.

    `max_turns=0` não serve de fixture aqui: `AgenteDeclarado.__post_init__`
    já recusa isso na hora de DECLARAR, antes de `Catalogo` entrar em cena —
    o que provaria a guarda errada. `ferramentas` inexistente é o caso que
    `AgenteDeclarado` não tem como enxergar sozinho (ele não conhece nenhum
    registro), e só `construir_agente` — chamado por `Catalogo.__post_init__`
    — descobre.
    """
    from orchestrator.agent.declarado import AgenteDeclarado

    quebrado = AgenteDeclarado(
        name="ferramenta_fantasma", system="s", kind="k", prompt="{x}",
        tipos=("A",), abstem_com="NAO_SEI", ferramentas=("nao_existe",),
    )

    with pytest.raises(ValueError):
        Catalogo(
            ferramentas=ToolRegistry([], contexto=None),
            regras=(),
            agentes=(quebrado,),
        )


def test_bloco_acha_por_nome_em_qualquer_das_duas_listas():
    assert CATALOGO.bloco("L1") is not None
    assert CATALOGO.bloco("triador") is not None
    assert CATALOGO.bloco("nao_existe") is None


def test_toda_REGRA_do_catalogo_CONSTROI_com_a_classe_declarada():
    """A propriedade central de `grill/ferramentas.py::_nomes_disponiveis`
    (Task 3): o enum que o chat oferece sai deste catálogo, então tudo que é
    proponível como REGRA precisa construir de verdade — `for` sobre
    `CATALOGO.regras`, não exemplo, para que uma regra nova entre coberta sem
    ninguém lembrar de acrescentar um caso aqui.

    `revisor` (a única REGRA de classe HUMANO) é a exceção deliberada: ele
    RECUSA construir por este caminho — ver `_revisor_precisa_da_fila` em
    `domains/registro.py`. Antes desta fatia ele "construía" devolvendo
    `RevisorHumano(fila=Fila.vazia())`, o que parecia funcionar e escondia
    que a fila real nunca chegava — o fallback silencioso que o spec proíbe,
    só que plausível. A expectativa agora é que ele LEVANTE, não que seja
    pulado sem sintoma.
    """
    for r in CATALOGO.regras:
        if r.cost_class is CostClass.HUMANO:
            with pytest.raises(ValueError, match="fila"):
                r.construir({})
            continue
        resolver = r.construir({})
        assert resolver.cost_class is r.cost_class, r.nome


def test_resumo_da_REGRA_bate_com_o_describe_do_resolver():
    """Duas fontes de verdade para a mesma frase divergiriam na primeira
    mudança. Isso importava pouco quando só a tela lia `resumo`; agora é
    literalmente o texto que `grill/ferramentas.py::_catalogo_em_texto` serve
    ao MODELO — um resumo desatualizado é uma instrução errada no prompt.
    """
    from orchestrator.review.fila import Fila
    from orchestrator.review.revisor import RevisorHumano

    for r in CATALOGO.regras:
        if r.cost_class is CostClass.HUMANO:
            # `revisor` não constrói por `r.construir` (teste acima); o
            # resolver de verdade é montado como quem compõe faz — com uma
            # fila de verdade, que `describe()` nem olha.
            resolver = RevisorHumano(fila=Fila.vazia())
        else:
            resolver = r.construir({})
        assert resolver.describe().summary == r.resumo, r.nome
