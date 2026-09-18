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
    from orchestrator.domains.reconciliation.agent.ferramentas import catalogo_de_ferramentas
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
        if r.obrigatorios:
            # A SEGUNDA exceção deliberada, e ela tem a mesma forma da primeira:
            # recusar alto em vez de construir algo que parece funcionar.
            #
            # Um bloco genérico (`igualdade`, `tolerancia`) não sabe de que
            # domínio é o workflow. Construir com `{}` produziria uma regra sem
            # campo nenhum, que casa zero — indistinguível de "não havia o que
            # casar", que é a falha silenciosa que este repositório mais teme.
            # A recusa NOMEIA o que falta, com os nomes que a tela mostra.
            with pytest.raises(ValueError, match="preenchido"):
                r.construir({})
            resolver = r.construir(_EXEMPLOS[r.nome])
        else:
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
    from orchestrator.domains.reconciliation.resolvers.tolerance import ToleranceMatcher
    from orchestrator.domains.registro import _param

    with pytest.raises(ValueError, match="ToleranceMatcher não tem campo"):
        _param(ToleranceMatcher, "campo_que_nao_existe", "x")


def test_resumo_da_REGRA_bate_com_o_describe_do_resolver():
    """Duas fontes de verdade para a mesma frase divergiriam na primeira
    mudança. Isso importava pouco quando só a tela lia `resumo`; agora é
    literalmente o texto que `grill/ferramentas.py::_catalogo_em_texto` serve
    ao MODELO — um resumo desatualizado é uma instrução errada no prompt.
    """
    from orchestrator.domains.reconciliation.revisor import RevisorHumano
    from orchestrator.review.fila import Fila

    for r in CATALOGO.regras:
        if r.cost_class is CostClass.HUMANO:
            # `revisor` não constrói por `r.construir` (teste acima); o
            # resolver de verdade é montado como quem compõe faz — com uma
            # fila de verdade, que `describe()` nem olha.
            resolver = RevisorHumano(fila=Fila.vazia())
        else:
            # Bloco genérico não constrói vazio — ver `_EXEMPLOS`. O resumo dele
            # não depende da configuração, mas construir é o único jeito de
            # perguntar ao `describe()`.
            resolver = r.construir(_EXEMPLOS[r.nome] if r.obrigatorios else {})
        assert resolver.describe().summary == r.resumo, r.nome


# ---------------------------------------------------------------------------
# O que cada bloco do catálogo EXIGE do `WorkItem.payload`.
#
# Tabela escrita à mão DE PROPÓSITO, e é o ponto do teste abaixo. A borda de
# execução (`api/app.py::_conferir_payload`) só é tão boa quanto as declarações
# atrás dela: um bloco que lê `be.document` e esquece de declarar não é
# recusado — ele devolve `200` com `rate: 0.0` e lacuna de 100% sobre dados que
# ninguém leu, que é a violação de "AUSENTE, não zero" pela porta dos fundos.
#
# Um bloco NOVO que não apareça aqui derruba o teste. Isso é deliberado: quem
# acrescentar um bloco precisa DECIDIR se ele lê campos tipados, em vez de
# herdar o default vazio sem pensar.
# ---------------------------------------------------------------------------

_SEM_EXIGENCIA: dict[str, type] = {}


def _exigencias_esperadas() -> dict[str, dict[str, type]]:
    from orchestrator.domains.procurement.workflow import PAYLOADS as COMPRAS
    from orchestrator.domains.reconciliation.models import PAYLOADS as CONCILIACAO

    return {
        # -- conciliação: leem `banco()`/`contabil()`, que devolvem tipado ----
        #
        # O L1 saiu desta lista, e a saída é o ganho da fatia das regras
        # genéricas: ele deixou de ser uma classe que lê `be.document` e virou
        # `regras.Igualdade` configurada com nomes de campo. Não exige tipo
        # nenhum, então roda sobre o dict de um CSV — e é por isso que
        # `test_payload_de_dict_contra_resolver_TIPADO_e_422` passou a nomear o
        # L2 no lugar dele.
        "L1": _SEM_EXIGENCIA,
        "L2": CONCILIACAO,
        "L3": CONCILIACAO,
        # `revisor` chama `divergencias(work)`, que lê `e.date`/`e.amount`.
        "revisor": CONCILIACAO,
        # -- compras: leem `r.payload.item` e `f.payload.preferido` -----------
        "preferido": COMPRAS,
        "anteriores": COMPRAS,
        # -- genéricas: leem o payload como MAPA DE CAMPOS, então não exigem
        # tipo nenhum. É o caso que o default de `ResolverDescription.payloads`
        # documenta, e é o que permite a MESMA regra rodar sobre a dataclass da
        # fonte sintética e sobre o dict que um CSV entrega. Foi por virar uma
        # destas que o L1 saiu da recusa de 422.
        "igualdade": _SEM_EXIGENCIA,
        "tolerancia": _SEM_EXIGENCIA,
        # Os tres destinos leem UM campo, pelo nome que a pessoa escolheu. Mesma
        # razao: quem le campo por nome roda sobre qualquer fonte.
        "filtro": _SEM_EXIGENCIA,
        "validacao": _SEM_EXIGENCIA,
        "condicao": _SEM_EXIGENCIA,
        # -- agentes declarados: montam o prompt a partir dos CAMPOS do item, e
        # `agent/declarado.py::_campos` aceita dataclass OU dict. Exigir tipo
        # aqui quebraria o caminho principal desta fatia — um CSV do usuário
        # com um agente do catálogo por cima.
        "investigador": _SEM_EXIGENCIA,
        "triador": _SEM_EXIGENCIA,
        "buscador": _SEM_EXIGENCIA,
    }


# Uma configuração VÁLIDA por bloco genérico, para os testes que precisam do
# `describe()` de um resolver construído.
#
# Mora no teste e não no catálogo de propósito: se o catálogo carregasse um
# exemplo, ele viraria o default na prática — a tela o ofereceria pré-preenchido
# —, e um default plausível de domínio errado casa zero em silêncio. Que é
# exatamente o que `ParametroDeRegra.obrigatorio` existe para impedir.
_EXEMPLOS: dict[str, dict] = {
    "igualdade": {
        "esquerda": "banco",
        "direita": "contabil",
        "campos": ("document", "amount=net_amount"),
    },
    "tolerancia": {
        "esquerda": "banco",
        "direita": "contabil",
        "chave": ("document",),
        "numerico": "amount=net_amount",
        "max_diferenca": 5,
    },
    # Os tres destinos compartilham o predicado, entao compartilham a forma da
    # configuracao. So `condicao` pede mais: o kind do ramo.
    "filtro": {"kind": "banco", "campo": "amount", "teste": "menor", "valor": "0"},
    "validacao": {"kind": "banco", "campo": "amount", "teste": "maior", "valor": "0"},
    "condicao": {
        "kind": "banco",
        "campo": "amount",
        "teste": "maior",
        "valor": "0",
        "produz": "suspeito",
    },
}


def _construir(bloco):
    """O resolver de verdade, montado como quem compõe monta."""
    from orchestrator.agent.declarado import ClienteDeValidacao
    from orchestrator.domains.reconciliation.revisor import RevisorHumano
    from orchestrator.review.fila import Fila

    if isinstance(bloco, AgenteDeclarado):
        return construir_agente(bloco, ClienteDeValidacao(), CATALOGO.ferramentas)
    if bloco.cost_class is CostClass.HUMANO:
        # `revisor` não constrói por `bloco.construir` — ver
        # `_revisor_precisa_da_fila`. A fila de verdade não muda `describe()`.
        return RevisorHumano(fila=Fila.vazia())
    if bloco.obrigatorios:
        return bloco.construir(_EXEMPLOS[bloco.nome])
    return bloco.construir({p.nome: p.default for p in bloco.parametros})


def _blocos():
    return [(r.nome, r) for r in CATALOGO.regras] + [(a.name, a) for a in CATALOGO.agentes]


def test_TODO_bloco_do_catalogo_declara_o_payload_que_exige():
    """A tabela acima contra o `describe()` de cada bloco, construído.

    Apagar `payloads=PAYLOADS` de um resolver derruba esta linha. Sem ela, a
    remoção deixava a suíte inteira verde e o workflow de compras sobre um CSV
    passava a devolver 200 com taxa zero.
    """
    esperado = _exigencias_esperadas()

    for nome, bloco in _blocos():
        assert nome in esperado, (
            f"bloco {nome!r} não está na tabela de exigências de payload. "
            f"Decida: ele lê CAMPOS do payload (declare `payloads=` no "
            f"`describe()` e registre aqui) ou trata o payload como mapa "
            f"(registre `_SEM_EXIGENCIA`)? Herdar o default vazio sem decidir "
            f"é como o 500 de `kind=banco` chegou até a borda."
        )
        assert _construir(bloco).describe().payloads == esperado[nome], nome


def test_a_tabela_de_exigencias_nao_tem_bloco_FANTASMA():
    """O outro lado: um nome que saiu do catálogo e ficou na tabela faria a
    tabela parecer completa enquanto protege um bloco que não existe mais."""
    assert set(_exigencias_esperadas()) == {nome for nome, _ in _blocos()}


# ---------------------------------------------------------------------------
# O que cada bloco do CATALOGO declara CONSUMIR. Pinado em tabela, e não
# derivado de `payloads`, porque são perguntas diferentes: `payloads` é "que
# TIPO exijo deste kind"; `consome` é "que KINDS pego do pool". O `triador` lê
# dicionário e não exige tipo nenhum, mas consome `issue` — sem esta tabela
# ele passaria como "vê o pool inteiro" por default, e a borda do `/runs` não
# teria como dizer que um CSV de lançamentos não é para ele.
# ---------------------------------------------------------------------------

CONSOME_ESPERADO: dict[str, frozenset[str]] = {
    # As genéricas consomem o que a CONFIGURAÇÃO disser — aqui, os kinds de
    # `_EXEMPLOS`. É a única linha desta tabela que depende de configuração e
    # não do resolver, e isso é a definição de bloco genérico.
    "igualdade": frozenset({"banco", "contabil"}),
    "tolerancia": frozenset({"banco", "contabil"}),
    # Uma ponta so: consomem o kind que `_EXEMPLOS` configurou.
    "filtro": frozenset({"banco"}),
    "validacao": frozenset({"banco"}),
    "condicao": frozenset({"banco"}),
    "L1": frozenset({"banco", "contabil"}),
    "L2": frozenset({"banco", "contabil"}),
    "L3": frozenset({"banco", "contabil"}),
    "revisor": frozenset({"banco", "contabil"}),
    "preferido": frozenset({"requisicao", "fornecedor"}),
    "anteriores": frozenset({"requisicao", "fornecedor"}),
    "investigador": frozenset({"banco"}),
    "triador": frozenset({"issue"}),
    "buscador": frozenset({"requisicao"}),
}


def test_TODO_bloco_do_catalogo_declara_o_que_CONSOME():
    """Bloco sem entrada aqui falha ALTO: quem escreve o próximo resolver
    decide o que ele consome, em vez de herdar "tudo" por default e ficar
    invisível para a guarda da borda."""
    for nome, bloco in _blocos():
        assert nome in CONSOME_ESPERADO, (
            f"{nome!r} não está na tabela CONSOME_ESPERADO. Decida quais kinds "
            f"ele pega do pool e acrescente a linha."
        )
        assert _construir(bloco).describe().consome == CONSOME_ESPERADO[nome], nome


def test_a_tabela_de_consumo_nao_tem_bloco_FANTASMA():
    """O outro lado, igual ao de `payloads`: um nome que saiu do catálogo e
    ficou na tabela protegeria um bloco que não existe mais."""
    assert set(CONSOME_ESPERADO) == {nome for nome, _ in _blocos()}


def test_agente_DECLARADO_consome_exatamente_o_kind_que_declara():
    """O kind de um `AgenteDeclarado` era APAGADO na construção — virava a
    closure de `units` — e `Agent.describe()` não tinha de onde lê-lo. Agora a
    spec o carrega, e é isso que a borda lê."""
    from orchestrator.agent.declarado import ClienteDeValidacao, construir_agente

    triador = next(a for a in CATALOGO.agentes if a.name == "triador")
    agente = construir_agente(triador, ClienteDeValidacao(), CATALOGO.ferramentas)
    assert agente.describe().consome == frozenset({"issue"})


def test_quem_exige_tipo_exige_o_TIPO_certo_e_nao_so_um_kind_qualquer():
    """A tabela compara dicionários inteiros, então um mapeamento trocado
    (`banco -> LedgerEntry`) também morre. Esta asserção explicita isso, porque
    é a metade da declaração que um leitor distraído ignoraria.

    Era o L1 que servia de exemplo aqui, e não serve mais: ele virou uma regra
    genérica e não exige tipo nenhum. O L2 assumiu o papel porque continua
    tipado — ele conta dias úteis, que é conhecimento de domínio e não
    configuração de campo. Trocar de exemplo é a manutenção certa; o que este
    teste protege é a exigência de TIPO, e enquanto existir um resolver tipado
    ela precisa de guarda.
    """
    from orchestrator.domains.reconciliation.models import BANCO, CONTABIL, BankEntry, LedgerEntry

    (_, l2) = next(b for b in _blocos() if b[0] == "L2")
    payloads = _construir(l2).describe().payloads

    assert payloads[BANCO] is BankEntry
    assert payloads[CONTABIL] is LedgerEntry
