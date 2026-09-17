"""O catálogo declarado: a prova de que a plataforma deixou de ser um
conciliador.

O teste que carrega o peso é `test_o_catalogo_e_PLANO_e_traz_tudo_junto`: se ele
voltar a listar só blocos de conciliação, a plataforma voltou a ser um cardápio.
Ele é o herdeiro de `test_os_TRES_dominios_se_declaram`, que fazia a mesma
pergunta contando DOMÍNIOS — e contar domínios deixou de significar alguma coisa
quando o catálogo ficou plano.
"""

import pytest

from orchestrator.agent.declarado import AgenteDeclarado, construir_agente
from orchestrator.agent.llm import FakeLLMClient
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.domains.registro import CATALOGO, Catalogo
from orchestrator.kernel.cost import CostClass


def test_o_conceito_de_DOMINIO_nao_existe_mais():
    """A metade "remover" da fatia, ancorada.

    Sem isto, um `Dominio` esquecido continuaria importável, e o próximo
    leitor não saberia se ele decide alguma coisa. Um conceito morto que
    ainda compila é o próximo a ser usado por engano.
    """
    import orchestrator.agent.declarado as declarado
    import orchestrator.domains.registro as registro

    assert not hasattr(declarado, "Dominio")
    assert not hasattr(registro, "DOMINIOS")


def test_TODO_agente_do_CATALOGO_CONSTROI():
    """"Validar é construir". `Catalogo.__post_init__` já faz isso na
    importação; este teste existe para que a falha apareça com nome de teste e
    não como ImportError no meio de outra suíte."""
    for a in CATALOGO.agentes:
        agente = construir_agente(a, FakeLLMClient([]), CATALOGO.ferramentas)
        assert agente.name == a.name


def test_nenhum_agente_confunde_ABSTENCAO_com_TIPO():
    """A invariante do P6.86 valendo para todos, não só para o `swe` onde ela
    foi descoberta — medindo, e depois de três execuções pagas."""
    for a in CATALOGO.agentes:
        assert a.abstem_com not in a.tipos, a.name


def test_as_ferramentas_do_CATALOGO_nao_sao_um_registro_executavel():
    """Um registro ligado a um `ToolContext` vazio listaria igual e executaria
    devolvendo nada. `ligado` torna a diferença verificável — e é o que separa
    COMPOR de EXECUTAR: quem executa chama `com_contexto`."""
    assert CATALOGO.ferramentas.names()
    assert not CATALOGO.ferramentas.ligado


def test_todo_agente_do_catalogo_so_declara_ferramentas_QUE_EXISTEM():
    disponiveis = set(CATALOGO.ferramentas.names())

    for a in CATALOGO.agentes:
        assert set(a.ferramentas) <= disponiveis, a.name


def test_um_TRABALHO_NOVO_nao_precisa_de_codigo_de_agente():
    """A prova da generalidade, do lado de fora.

    Declarar um agente funcional para um tipo de trabalho que a plataforma
    nunca viu é DADO: nenhuma função `units`, `parse` ou `abstain` é escrita.
    Se isto exigisse Python, o catálogo voltaria a ser um cardápio de coisas
    prontas.
    """
    novo = AgenteDeclarado(
        name="classificador",
        system="classifique o chamado",
        kind="chamado",
        prompt="{assunto}\n\n{descricao}",
        tipos=("INCIDENTE", "SOLICITACAO"),
        abstem_com="NAO_SEI",
    )

    agente = construir_agente(novo, FakeLLMClient([]))

    assert agente.name == "classificador"


def test_o_catalogo_e_PLANO_e_traz_tudo_junto():
    """Um catálogo só, sem agrupamento. É o quadro em branco do §0.1.

    O teste que carrega o peso deste arquivo, e o herdeiro direto de
    `test_os_TRES_dominios_se_declaram`: a pergunta do dono era "por que só tem
    blocos de conciliação?", e a resposta verificável não é quantos domínios
    existem — é que os blocos das TRÊS origens estão na mesma paleta, nomeados.

    3 regras de conciliação + 2 de compras + o `revisor`, e um agente de cada
    origem.
    """
    nomes_de_regra = {r.nome for r in CATALOGO.regras}

    assert {"L1", "L2", "L3", "preferido", "anteriores"} <= nomes_de_regra
    assert {a.name for a in CATALOGO.agentes} == {"investigador", "triador", "buscador"}


def test_o_catalogo_carrega_o_degrau_HUMANO():
    """O `revisor` existia só no catálogo do grill, e domínio nenhum o carregava.

    Fundir os dois sem ele perderia o degrau que FECHA a cascata — e a
    invariante "proposta não resolve" depende de existir alguém que resolva.
    """
    revisor = next(r for r in CATALOGO.regras if r.nome == "revisor")

    assert revisor.cost_class is CostClass.HUMANO


def test_as_ferramentas_das_TRES_origens_estao_no_MESMO_registro():
    """"Todas as nossas tools disponíveis pra ele" — o pedido, virado teste.

    A conferência é contra as origens, não contra um número: `>= 6` passaria
    com o registro do `swe` sozinho somado a qualquer coisa, e o defeito que
    este teste existe para pegar é justamente uma origem PERDIDA na fusão.
    """
    from orchestrator.conciliacao.ferramentas import catalogo_de_ferramentas
    from orchestrator.domains.swe.workflow import ferramentas as ferramentas_swe

    nomes = set(CATALOGO.ferramentas.names())
    das_origens = set(catalogo_de_ferramentas().names()) | set(ferramentas_swe().names())

    assert nomes == das_origens
    assert "contar_palavras" in nomes  # veio do swe
    assert len(nomes) == 6  # as 5 da conciliação mais a do swe


def test_o_catalogo_RECUSA_bloco_com_nome_repetido():
    """A guarda que migrou da validação por domínio, e que fica MAIS perigosa
    aqui.

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
    """Quem compõe conhece o NOME, não a natureza — e recebe o bloco CERTO.

    `is not None` provaria só que alguma coisa voltou: um `bloco()` que
    devolvesse sempre a primeira regra passaria, e a cascata montada a partir
    dele rodaria um resolver que ninguém escolheu. A identidade é o que torna
    isso impossível.
    """
    from orchestrator.agent.declarado import AgenteDeclarado, RegraDisponivel

    l1 = CATALOGO.bloco("L1")
    triador = CATALOGO.bloco("triador")

    assert isinstance(l1, RegraDisponivel) and l1.nome == "L1"
    assert isinstance(triador, AgenteDeclarado) and triador.name == "triador"
    assert l1 is next(r for r in CATALOGO.regras if r.nome == "L1")
    assert triador is next(a for a in CATALOGO.agentes if a.name == "triador")
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


def test_parametro_INEXISTENTE_no_resolver_explode_NOMEANDO_o_resolver():
    """A guarda que vive em `_param`, e o TEXTO dela.

    O catálogo lê o default do próprio resolver, então renomear um campo lá
    precisa explodir aqui, na importação — nunca virar uma tela oferecendo um
    parâmetro que o construtor não aceita. `campos[nome]` sozinho já levantaria,
    mas um `KeyError: 'max_cents'` no meio de um import não diz de QUE resolver
    o campo sumiu, que é a única informação capaz de apontar a linha a mudar.

    Este teste é o herdeiro direto de
    `test_parametro_inexistente_no_resolver_explode_na_construcao_do_catalogo`,
    que travava a mesma mensagem em `grill.catalogo._param` — o `_param` que
    esta fatia removeu junto com o cardápio do grill.
    """
    from orchestrator.domains.registro import _param
    from orchestrator.matching.tolerance import ToleranceMatcher

    with pytest.raises(ValueError, match="ToleranceMatcher não tem campo"):
        _param(ToleranceMatcher, "campo_que_nao_existe", "x")


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
