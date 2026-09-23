"""O catálogo: tudo que dá para compor, num lugar só.

**O que este módulo era e por que deixou de ser.** Ele declarava DOMÍNIOS —
`conciliacao`, `swe`, `procurement` —, cada um com seus `kinds`, ferramentas,
agentes e regras. A tela perguntava o domínio ANTES de mostrar qualquer bloco, e
a paleta saía particionada por essa resposta.

A partição não pagava o que custava. Ela existia para impedir uma cascata que
mistura um resolver de conciliação com um de compras — que não é ruim, é vazia
de sentido, porque o segundo roda sobre um pool que o primeiro nem enxerga. Só
que a fatia do grafo passou a dizer isso melhor e no lugar certo:
`Stage.consome`/`Stage.produz` declara a fiação POR DEGRAU e
`WorkflowDefinition.__post_init__` recusa um grafo cujos kinds não conectam.
Aquilo valida o grafo que VAI RODAR; a partição validava um índice de catálogo.

Sobrou um quadro em branco com uma paleta só — que é o que o dono pediu quando
perguntou por que só havia blocos de conciliação.

**Agente é DADO; regra é CÓDIGO com parâmetros expostos.** Casar por documento e
valor é lógica de domínio, e não há declaração que a substitua — fingir que há
produziria uma linguagem de regras pela metade. O que a composição escolhe é
QUAIS regras entram e com que parâmetros, nunca o corpo delas.

É a assimetria que faz a plataforma ser geral sem virar um gerador de código:
o caro (agente) é declarativo porque precisa ser composto por quem não programa;
o barato (regra) é código porque é onde a lógica do negócio realmente mora.
"""

from dataclasses import dataclass
from typing import Any, NoReturn

from orchestrator.agent.declarado import (
    AgenteDeclarado,
    ClienteDeValidacao,
    ParametroDeRegra,
    RegraDisponivel,
    ValorDeParametro,
    construir_agente,
)
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.domains.procurement.workflow import (
    ComprasAnteriores,
    FornecedorPreferido,
)
from orchestrator.domains.reconciliation.agent.ferramentas import catalogo_de_ferramentas
from orchestrator.domains.reconciliation.resolvers.grouping import GroupingMatcher
from orchestrator.domains.reconciliation.resolvers.tolerance import ToleranceMatcher
from orchestrator.domains.reconciliation.workflow import l1_exato
from orchestrator.domains.swe.workflow import ISSUE, PROMPT
from orchestrator.domains.swe.workflow import ferramentas as ferramentas_swe
from orchestrator.kernel.cost import CostClass


@dataclass(frozen=True)
class Catalogo:
    """Tudo que dá para compor, junto, sem agrupamento.

    **Por que sem `kinds`.** O agrupamento por domínio existia para impedir uma
    cascata que mistura kinds que não conversam. Continua sendo um problema
    real, e a fatia do grafo passou a resolvê-lo onde ele acontece:
    `Stage.consome`/`Stage.produz` declara a fiação POR DEGRAU e
    `WorkflowDefinition.__post_init__` recusa um grafo cujos kinds não
    conectam. Aquilo valida o grafo que vai rodar; o agrupamento validava uma
    partição de catálogo. O agrupamento é resto.

    **O `revisor` mora aqui, e o nome do tipo mente um pouco.** Ele é classe
    `HUMANO`, não regra. `RegraDisponivel` descreve "bloco determinístico com
    parâmetros ajustáveis", o que serve de forma, não de nome. Ele vivia só no
    catálogo do grill, e domínio nenhum o carregava — a lacuna estava
    registrada em `App.tsx`. Fundir sem ele perderia o degrau que FECHA a
    cascata.
    """

    ferramentas: ToolRegistry
    regras: tuple[RegraDisponivel, ...] = ()
    agentes: tuple[AgenteDeclarado, ...] = ()

    def __post_init__(self) -> None:
        # Guarda 1, e ela é mais perigosa aqui do que quando valia por domínio:
        # a composição indexa bloco por NOME, e dois iguais fariam a cascata
        # depender de quem foi procurado primeiro. Num catálogo plano a colisão
        # deixa de ser possível só entre blocos da mesma origem.
        nomes = [r.nome for r in self.regras] + [a.name for a in self.agentes]
        repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
        if repetidos:
            raise ValueError(f"catálogo com nome repetido entre blocos: {repetidos}")
        # Guarda 2: VALIDAR É CONSTRUIR. Sem isto, uma declaração inválida só
        # falha ao EXECUTAR — depois de a pessoa ter montado a cascata inteira
        # e clicado em rodar.
        for a in self.agentes:
            construir_agente(a, ClienteDeValidacao(), self.ferramentas)

    def bloco(self, nome: str) -> "RegraDisponivel | AgenteDeclarado | None":
        """O bloco com este nome, venha ele de qual lista vier.

        Existe porque quem compõe conhece o NOME, não a natureza: o
        entrevistador recebe "L2" do modelo e a tela recebe "L2" de um clique,
        e nenhum dos dois deveria precisar saber em que lista procurar.
        """
        for r in self.regras:
            if r.nome == nome:
                return r
        for a in self.agentes:
            if a.name == nome:
                return a
        return None


def _param(cls: type, nome: str, descricao: str) -> ParametroDeRegra:
    """Lê o default do PRÓPRIO resolver.

    Renomear o campo lá explode AQUI, no import, e não numa tela que oferece um
    parâmetro que o construtor não aceita.

    **A recusa é EXPLÍCITA, e o texto é o que ela entrega.** `campos[nome]`
    sozinho já levantaria — mas um `KeyError: 'max_cents'` no meio de um import
    não diz de que resolver o campo sumiu, e é justamente esse nome que aponta
    para a linha que precisa mudar. Falhar alto e falhar LEGÍVEL são a mesma
    exigência neste repositório.
    """
    import dataclasses

    campos = {f.name: f for f in dataclasses.fields(cls)}
    if nome not in campos:
        raise ValueError(f"{cls.__name__} não tem campo {nome!r}")
    return ParametroDeRegra(nome=nome, default=campos[nome].default, descricao=descricao)


def _todas_as_ferramentas() -> ToolRegistry:
    """Um registro com as ferramentas de todas as origens. É CATÁLOGO.

    `register` já recusa nome repetido, então uma colisão entre origens falha
    na importação em vez de uma das duas ganhar em silêncio.

    **Sem contexto, e a distinção é a que `ToolRegistry` fez questão de tornar
    visível.** `contexto=None` significaria "ligado, e os dados são `None`" —
    uma ferramenta de conciliação chamada assim estouraria em `None.bank`. Um
    registro NÃO LIGADO recusa com texto. Quem executa chama `com_contexto`.
    """
    junto = ToolRegistry()
    for origem in (catalogo_de_ferramentas(), ferramentas_swe()):
        for nome in origem.names():
            junto.register(origem.spec(nome))
    return junto


def _revisor_precisa_da_fila(parametros: dict[str, ValorDeParametro]) -> NoReturn:
    """`revisor` não constrói por esta via — e é ERRO, não decoração.

    `RegraDisponivel.construir` tem assinatura uniforme `(parametros) ->
    Resolver` (ver o docstring da classe), sem onde receber a fila REAL de
    decisões já tomadas. Um `RevisorHumano(fila=Fila.vazia())` aqui
    CONSTRUIRIA — pareceria funcionar, a cascata ficaria "desenhável" — e
    decisões aprovadas nunca chegariam à execução, sem nada avisar: o
    fallback silencioso que o spec proíbe, só que plausível.

    Quem compõe uma cascata com um bloco `CostClass.HUMANO` precisa
    reconhecer a classe e montar o resolver direto, com a fila de verdade. Os
    dois consumidores fazem isso e são as duas referências vivas:
    `grill.receita.construir` (o chat) e `authoring.composicao.
    construir_composicao` (o canvas). O segundo NÃO ramificava, e o sintoma
    foi exato: o `revisor` aparecia na paleta e era o único bloco que "Compor
    e validar" recusava, com esta mensagem — escrita para quem implementa —
    vazando para a tela.
    """
    raise ValueError(
        "'revisor' não pode ser construído por RegraDisponivel.construir: "
        "esse degrau depende da fila REAL de decisões, que a assinatura "
        "(parametros) -> Resolver não tem como receber. Quem compõe precisa "
        "reconhecer cost_class is CostClass.HUMANO e montar "
        "RevisorHumano(fila=...) direto, com a fila de verdade — nunca "
        "chamar este `construir`"
    )


_PROMPT_INVESTIGADOR = """Você investiga divergências de conciliação bancária.

Responda APENAS com um objeto JSON:
{"tipo": <um dos tipos>, "explicacao": <texto curto>,
 "evidencia": [<strings>], "confianca": "ALTA"|"MEDIA"|"BAIXA"}

Use as ferramentas para buscar o que falta. Não saber é resposta válida:
responda NAO_IDENTIFICADO com confiança BAIXA."""

_PROMPT_COMPRADOR = """Você procura fornecedor para uma requisição de compra.

Responda APENAS com um objeto JSON:
{"tipo": "FORNECEDOR_NOVO"|"REQUISICAO_INVIABIL"|"NAO_SEI",
 "explicacao": <texto curto>, "evidencia": [<strings>],
 "confianca": "ALTA"|"MEDIA"|"BAIXA"}

Não saber é resposta válida: responda NAO_SEI com confiança BAIXA."""


# ---------------------------------------------------------------------------
# O catálogo. Os comentários de origem ("conciliação", "compras") são HISTÓRIA,
# não estrutura: nada lê essas fronteiras, e é essa a diferença entre este
# arquivo e o que havia antes dele.
#
# `redacao` NÃO aparece aqui, e a ausência é deliberada — não esquecimento.
# `domains/redacao/workflow.py` roda (`definition(cliente)` + `pool(...)`,
# exercitado por `tests/domains/test_redacao.py`), mas os três degraus dele são
# `Tarefa`: cada um TRANSFORMA o item num item de outro `kind` para o próximo
# consumir, em vez de julgar o item que recebeu. Nem `AgenteDeclarado` nem
# `RegraDisponivel` sabem descrever isso — os dois descrevem um resolver que
# decide sobre UM item e devolve `Proposal`/`Resolution` a respeito DELE.
# Catalogá-lo hoje exigiria mentir sobre o que ele faz. Ensinar
# `AgenteDeclarado` a declarar `produz` é a metade X8 da lacuna de `kind` —
# ainda reservada. A metade X7 (`consome` declarado, derivado por
# `consome_de` e conferido na borda do `/runs`) fechou; ver P9.1 em
# `docs/superpowers/DECISOES.md`.
# ---------------------------------------------------------------------------

def _lista(valor: ValorDeParametro | None) -> tuple[str, ...]:
    """A lista de campos como o construtor a quer.

    O JSON transporta `list`, o dataclass declara `tuple`, e a tela manda o que
    a pessoa digitou. Coagir AQUI, na borda entre os dois, em vez de aceitar os
    dois lá dentro: um `Igualdade` com `campos` ora tupla ora lista deixaria de
    ser hasheável pela metade, e o erro apareceria longe da causa.
    """
    if valor is None or valor == "":
        return ()
    if isinstance(valor, str):
        return (valor,)
    return tuple(str(v) for v in valor)


def _exige(bloco: str, p: dict[str, ValorDeParametro], nomes: tuple[str, ...]) -> None:
    """Recusa ANTES de construir, nomeando o que a pessoa não preencheu.

    As regras genéricas já recusariam sozinhas — `Igualdade` levanta com
    `campos` vazio. O que elas não sabem é como a TELA chama as coisas: a
    mensagem delas fala de argumento de construtor, e quem lê está olhando um
    formulário. Esta recusa usa os nomes do catálogo, que são os nomes que a
    pessoa acabou de ver.
    """
    faltam = [n for n in nomes if not p.get(n)]
    if faltam:
        raise ValueError(
            f"{bloco!r} precisa de {faltam} preenchido(s). este é um bloco "
            f"genérico: ele não sabe de que domínio é o seu workflow, então "
            f"quem diz em quais campos ele casa é você"
        )


def _igualdade(p: dict[str, ValorDeParametro]) -> Any:
    from orchestrator.regras import Igualdade

    _exige("igualdade", p, ("esquerda", "direita", "campos"))
    return Igualdade(
        esquerda=str(p.get("esquerda", "")),
        direita=str(p.get("direita", "")),
        campos=_lista(p.get("campos")),
        modulo=_lista(p.get("modulo")),
    )


# Os testes que um predicado aceita, na descrição que a tela mostra. Derivado do
# enum e não escrito à mão: um teste novo aparece na tela sozinho, e um removido
# some — a lista digitada aqui seria a segunda fonte de verdade que envelheceria
# na primeira mudança.
def _testes_disponiveis() -> str:
    from orchestrator.regras import Comparacao

    return " | ".join(c.value for c in Comparacao)


def _predicado_params(obrigatorio_kind: str) -> tuple[ParametroDeRegra, ...]:
    """Os três parâmetros que os blocos de uma ponta só compartilham.

    Escritos uma vez porque são o MESMO eixo: "limiar" e "padrão" não são dois
    blocos, são este parâmetro com um `teste` diferente. Repeti-los por bloco
    faria a descrição divergir entre filtro, validação e condição.
    """
    return (
        ParametroDeRegra("kind", "", obrigatorio_kind, obrigatorio=True),
        ParametroDeRegra("campo", "", "o campo sobre o qual perguntar", obrigatorio=True),
        ParametroDeRegra("teste", "", f"a pergunta: {_testes_disponiveis()}", obrigatorio=True),
        ParametroDeRegra(
            "valor",
            "",
            "com o que comparar. vazio só para os testes `vazio` e `preenchido`",
        ),
    )


def _filtro(p: dict[str, ValorDeParametro]) -> Any:
    from orchestrator.regras import Filtro

    _exige("filtro", p, ("kind", "campo", "teste"))
    return Filtro(
        kind=str(p.get("kind", "")),
        campo=str(p.get("campo", "")),
        teste=str(p.get("teste", "")),
        valor=str(p.get("valor", "")),
        motivo=str(p.get("motivo") or "descartado por filtro"),
    )


def _validacao(p: dict[str, ValorDeParametro]) -> Any:
    from orchestrator.regras import Validacao

    _exige("validacao", p, ("kind", "campo", "teste"))
    return Validacao(
        kind=str(p.get("kind", "")),
        campo=str(p.get("campo", "")),
        teste=str(p.get("teste", "")),
        valor=str(p.get("valor", "")),
        tipo=str(p.get("tipo") or "FORA_DA_POLITICA"),
    )


def _condicao(p: dict[str, ValorDeParametro]) -> Any:
    from orchestrator.regras import Condicao

    _exige("condicao", p, ("kind", "campo", "teste", "produz"))
    return Condicao(
        kind=str(p.get("kind", "")),
        campo=str(p.get("campo", "")),
        teste=str(p.get("teste", "")),
        valor=str(p.get("valor", "")),
        produz=str(p.get("produz", "")),
    )


def _agrupamento(p: dict[str, ValorDeParametro]) -> Any:
    from orchestrator.regras import Agrupamento

    _exige("agrupamento", p, ("esquerda", "direita", "chave", "soma"))
    return Agrupamento(
        esquerda=str(p.get("esquerda", "")),
        direita=str(p.get("direita", "")),
        chave=_lista(p.get("chave")),
        soma=str(p.get("soma", "")),
        max_itens=int(p.get("max_itens", 4) or 4),
        max_diferenca=int(p.get("max_diferenca", 0) or 0),
        max_candidatos=int(p.get("max_candidatos", 24) or 24),
    )


def _enriquecimento(p: dict[str, ValorDeParametro]) -> Any:
    """O bloco que busca o detalhe de cada item.

    `token_env` vazio vira `None`, e não `""`: a tela manda string vazia quando
    o campo não foi preenchido, e `""` como NOME de variável pediria uma
    variável chamada vazio — `VariavelAusente('')`, que não diz nada a ninguém.
    """
    from orchestrator.sources.enriquecimento import Enriquecimento

    _exige("enriquecer", p, ("kind", "produz", "url"))
    token = str(p.get("token_env", "")).strip()
    return Enriquecimento(
        kind=str(p.get("kind", "")),
        produz=str(p.get("produz", "")),
        url=str(p.get("url", "")),
        token_env=token or None,
        caminho=str(p.get("caminho", "")),
    )


def _entrada(p: dict[str, ValorDeParametro]) -> Any:
    """O bloco de ENTRADA: uma fonte que vira degrau.

    A fonte não é lida aqui — `Entrada.resolve` lê. Compor não pode tocar em
    banco nem em rede: `/api/composicoes` valida sem executar.
    """
    from orchestrator.sources.bloco import Entrada
    from orchestrator.sources.fabrica import fonte_de_parametros

    _exige("entrada", p, ("tipo", "kind"))
    return Entrada(fonte=fonte_de_parametros(dict(p)), produz=(str(p["kind"]),))


def _paralelo(p: dict[str, ValorDeParametro]) -> Any:
    from orchestrator.regras import Paralelo

    _exige("paralelo", p, ("kind", "ramos"))
    return Paralelo(kind=str(p.get("kind", "")), ramos=_lista(p.get("ramos")))


def _juncao(p: dict[str, ValorDeParametro]) -> Any:
    from orchestrator.regras import Juncao

    _exige("juncao", p, ("ramos", "produz"))
    return Juncao(ramos=_lista(p.get("ramos")), produz=str(p.get("produz", "")))


def _tabela(p: dict[str, ValorDeParametro]) -> Any:
    from orchestrator.regras import Tabela

    _exige("tabela", p, ("kind", "campo", "de_para"))
    return Tabela(
        kind=str(p.get("kind", "")),
        campo=str(p.get("campo", "")),
        de_para=_lista(p.get("de_para")),
    )


def _tolerancia(p: dict[str, ValorDeParametro]) -> Any:
    from orchestrator.regras import Tolerancia

    _exige("tolerancia", p, ("esquerda", "direita", "chave", "numerico"))
    return Tolerancia(
        esquerda=str(p.get("esquerda", "")),
        direita=str(p.get("direita", "")),
        chave=_lista(p.get("chave")),
        numerico=str(p.get("numerico", "")),
        max_diferenca=int(p.get("max_diferenca", 0) or 0),
        data=str(p.get("data", "")),
        max_dias=int(p.get("max_dias", 0) or 0),
    )


CATALOGO = Catalogo(
    ferramentas=_todas_as_ferramentas(),
    regras=(
        # -- genéricas: servem a qualquer domínio ----------------------------
        #
        # Estas duas não pertencem a domínio nenhum: elas casam por NOME DE
        # CAMPO, e quem diz os nomes é quem monta o workflow na tela. É a
        # diferença entre um catálogo que oferece "L1, L2, L3" — que só
        # significam alguma coisa para quem concilia extrato bancário — e um que
        # oferece peças com as quais se monta o L1.
        #
        # Nascem SEM default utilizável de propósito. "banco" e "contabil" como
        # default seriam conciliação vazando para dentro da peça que existe para
        # não ter domínio, e um campo pré-preenchido com o nome errado casa zero
        # em silêncio — que é pior do que recusar dizendo o que falta.
        RegraDisponivel(
            nome="igualdade",
            rotulo="Exact match",
            categoria="MATCHING",
            cost_class=CostClass.REGRA,
            resumo="os campos escolhidos coincidem exatamente nos dois lados",
            parametros=(
                ParametroDeRegra("esquerda", "", "o kind de um lado", obrigatorio=True),
                ParametroDeRegra("direita", "", "o kind do outro lado", obrigatorio=True),
                ParametroDeRegra(
                    "campos",
                    (),
                    "campos que precisam bater. 'documento' quando os dois lados "
                    "chamam igual; 'valor=total' quando não",
                    obrigatorio=True,
                ),
                ParametroDeRegra(
                    "modulo",
                    (),
                    "campos comparados por módulo, para quando um lado registra "
                    "com sinal invertido",
                ),
            ),
            construir=lambda p: _igualdade(p),
        ),
        RegraDisponivel(
            nome="tolerancia",
            rotulo="Tolerance",
            categoria="MATCHING",
            cost_class=CostClass.REGRA,
            resumo="chave exata, com folga de valor e de dias corridos",
            parametros=(
                ParametroDeRegra("esquerda", "", "o kind de um lado", obrigatorio=True),
                ParametroDeRegra("direita", "", "o kind do outro lado", obrigatorio=True),
                ParametroDeRegra(
                    "chave", (), "campos que precisam bater exatamente", obrigatorio=True
                ),
                ParametroDeRegra(
                    "numerico", "", "o campo cuja diferença tem folga", obrigatorio=True
                ),
                ParametroDeRegra("max_diferenca", 0, "folga máxima desse campo"),
                ParametroDeRegra("data", "", "o campo de data, ou vazio para ignorar"),
                ParametroDeRegra("max_dias", 0, "folga máxima entre as datas, em dias corridos"),
            ),
            construir=lambda p: _tolerancia(p),
        ),
        RegraDisponivel(
            nome="agrupamento",
            rotulo="Grouping",
            categoria="MATCHING",
            cost_class=CostClass.REGRA,
            resumo="um item de um lado cobrindo N do outro, pela soma",
            parametros=(
                ParametroDeRegra("esquerda", "", "o kind do lado que tem UM", obrigatorio=True),
                ParametroDeRegra("direita", "", "o kind do lado que tem N", obrigatorio=True),
                ParametroDeRegra(
                    "chave", (), "campos que agrupam os candidatos", obrigatorio=True
                ),
                ParametroDeRegra(
                    "soma", "", "o campo que precisa somar (ex.: valor=total)", obrigatorio=True
                ),
                ParametroDeRegra("max_itens", 4, "quantos itens no máximo por grupo"),
                ParametroDeRegra("max_diferenca", 0, "folga aceita na soma"),
                ParametroDeRegra(
                    "max_candidatos", 24, "teto de combinações testadas; a busca é combinatória"
                ),
            ),
            construir=lambda p: _agrupamento(p),
        ),
        RegraDisponivel(
            nome="tabela",
            rotulo="Switch",
            categoria="CONTROL",
            cost_class=CostClass.REGRA,
            resumo="o valor do campo escolhe o ramo",
            parametros=(
                ParametroDeRegra("kind", "", "o kind que entra neste bloco", obrigatorio=True),
                ParametroDeRegra("campo", "", "o campo cujo valor decide", obrigatorio=True),
                ParametroDeRegra(
                    "de_para",
                    (),
                    "uma rota por valor: PJ=empresa, PF=pessoa. valor fora da "
                    "tabela não é tocado",
                    obrigatorio=True,
                ),
            ),
            construir=lambda p: _tabela(p),
        ),
        # A ENTRADA: a fonte como degrau.
        #
        # Enquanto a fonte era escolhida na hora de rodar, o workflow não sabia
        # de onde vinha o dado — e um run disparado por webhook não tem ninguém
        # para escolher. Este bloco é o que torna um workflow autossuficiente.
        RegraDisponivel(
            nome="entrada",
            cost_class=CostClass.REGRA,
            resumo="lê a fonte e põe o trabalho no pool",
            rotulo="Input",
            categoria="WORKFLOW",
            parametros=(
                ParametroDeRegra(
                    "tipo", "", "de onde vem: postgres | http", obrigatorio=True
                ),
                ParametroDeRegra(
                    "kind", "", "que tipo de item esta fonte entrega", obrigatorio=True
                ),
                ParametroDeRegra("campo_id", "", "o campo que identifica cada item"),
                ParametroDeRegra("url", "", "http: o endereço da API"),
                ParametroDeRegra(
                    "token_env", "", "http: o NOME da variável de ambiente com o token"
                ),
                ParametroDeRegra("caminho", "", "http: onde a lista está no corpo"),
                ParametroDeRegra(
                    "dsn_env", "", "postgres: o NOME da variável com a string de conexão"
                ),
                ParametroDeRegra("query", "", "postgres: a consulta"),
            ),
            construir=lambda p: _entrada(p),
        ),
        # ABRIR e REUNIR — o que rotear NÃO faz.
        #
        # `condicao` e `tabela` escolhem UM ramo por item. O caso mais comum de
        # paralelismo é o oposto: toda transação passa pela checagem de fraude E
        # pela de KYC, e depois as duas se reencontram. Nenhum roteador faz
        # isso, porque roteador escolhe.
        # O bloco que faltava entre `Input` e a decisão: buscar, para CADA item,
        # o detalhe que a lista não trouxe. Sem ele, a única saída era pagar um
        # turno de modelo para executar um GET que não decide nada.
        RegraDisponivel(
            nome="enriquecer",
            rotulo="Enrich",
            categoria="DATA",
            cost_class=CostClass.REGRA,
            resumo="busca numa API o detalhe de cada item e funde no payload",
            parametros=(
                ParametroDeRegra("kind", "", "o kind que entra neste bloco", obrigatorio=True),
                ParametroDeRegra(
                    "produz", "", "o kind que sai, já enriquecido", obrigatorio=True
                ),
                ParametroDeRegra(
                    "url",
                    "",
                    "a url, com {campo} do item — ex.: https://api/v1/casos/{id}",
                    obrigatorio=True,
                ),
                ParametroDeRegra(
                    "token_env", "", "o NOME da variável de ambiente com o bearer"
                ),
                ParametroDeRegra(
                    "caminho", "", "onde o objeto está no corpo (vazio = o corpo inteiro)"
                ),
            ),
            construir=lambda p: _enriquecimento(p),
        ),
        RegraDisponivel(
            nome="paralelo",
            cost_class=CostClass.REGRA,
            resumo="todo item segue por todos os ramos ao mesmo tempo",
            rotulo="Parallel",
            categoria="CONTROL",
            parametros=(
                ParametroDeRegra("kind", "", "o kind que entra neste bloco", obrigatorio=True),
                ParametroDeRegra(
                    "ramos",
                    (),
                    "os kinds dos ramos, pelo menos dois: fraude, kyc",
                    obrigatorio=True,
                ),
            ),
            construir=lambda p: _paralelo(p),
        ),
        RegraDisponivel(
            nome="juncao",
            cost_class=CostClass.REGRA,
            resumo="reúne os ramos de um mesmo item num só",
            rotulo="Merge",
            categoria="CONTROL",
            parametros=(
                ParametroDeRegra(
                    "ramos", (), "os kinds a reunir, pelo menos dois", obrigatorio=True
                ),
                ParametroDeRegra(
                    "produz",
                    "",
                    "o kind que sai da junção. Só junta quando TODOS os ramos chegaram",
                    obrigatorio=True,
                ),
            ),
            construir=lambda p: _juncao(p),
        ),
        # Os TRÊS DESTINOS de um item que passa num teste. O que muda entre eles
        # não é a pergunta — é o que acontece com o item, e são três verbos
        # diferentes no pool:
        #
        #   filtro     RESOLVE  o item sai do pool, com o motivo no trace
        #   validacao  PROPÕE   o item fica, e um humano decide
        #   condicao   ROTEIA   o item sai como um kind e volta como outro
        #
        # Um bloco só com um parâmetro "o que fazer" esconderia qual dos três
        # aconteceu — e os três mexem no pool de maneiras que não se confundem.
        RegraDisponivel(
            nome="filtro",
            rotulo="Filter",
            categoria="COMPUTE",
            cost_class=CostClass.REGRA,
            resumo="descarta do pool o item que passa no teste",
            parametros=(
                *_predicado_params("o kind que este bloco filtra"),
                ParametroDeRegra("motivo", "", "o que o trace vai dizer sobre o descarte"),
            ),
            construir=lambda p: _filtro(p),
        ),
        RegraDisponivel(
            nome="validacao",
            rotulo="Validate",
            categoria="COMPUTE",
            cost_class=CostClass.REGRA,
            resumo="quem falha o teste vira proposta para revisão humana",
            parametros=(
                *_predicado_params("o kind que este bloco confere"),
                ParametroDeRegra(
                    "tipo", "", "o rótulo que o humano lê na fila (ex.: FORA_DA_POLITICA)"
                ),
            ),
            construir=lambda p: _validacao(p),
        ),
        RegraDisponivel(
            nome="condicao",
            rotulo="Condition",
            categoria="CONTROL",
            cost_class=CostClass.REGRA,
            resumo="quem passa no teste segue por outro ramo",
            parametros=(
                *_predicado_params("o kind que entra neste bloco"),
                ParametroDeRegra(
                    "produz",
                    "",
                    "o kind do ramo. o degrau que o consome só roda quando houver item dele",
                    obrigatorio=True,
                ),
            ),
            construir=lambda p: _condicao(p),
        ),
        # -- conciliação: a implementação de referência (§1.3) --------------
        RegraDisponivel(
            nome="L1",
            rotulo="Exact (L1)",
            categoria="DOMAIN",
            cost_class=CostClass.REGRA,
            resumo="documento, valor e data coincidem exatamente",
            # `l1_exato()` e não `ExactMatcher()`: o L1 executado É a regra
            # genérica configurada, e o bloco que a tela oferece tem de ser o
            # mesmo objeto. Duas construções diferentes com o mesmo nome fariam
            # a composição rodar algo que o catálogo não descreve — e o único
            # sintoma seria um número diferente do relatório.
            construir=lambda p: l1_exato(),
        ),
        RegraDisponivel(
            nome="L2",
            rotulo="Tolerance (L2)",
            categoria="DOMAIN",
            cost_class=CostClass.REGRA,
            resumo="mesmo documento, com folga de valor e dias úteis",
            parametros=(
                _param(ToleranceMatcher, "max_cents", "folga máxima de valor, em centavos"),
                _param(
                    ToleranceMatcher,
                    "max_business_days",
                    "folga máxima entre as datas, em dias úteis",
                ),
            ),
            construir=lambda p: ToleranceMatcher(**p),
        ),
        RegraDisponivel(
            nome="L3",
            rotulo="Grouping (L3)",
            categoria="DOMAIN",
            cost_class=CostClass.REGRA,
            resumo="um lançamento bancário cobrindo N contábeis do mesmo fornecedor",
            parametros=(
                _param(GroupingMatcher, "max_group_size", "quantos contábeis no máximo"),
                _param(GroupingMatcher, "max_business_days", "folga entre as datas"),
                _param(GroupingMatcher, "max_candidates", "teto de combinações testadas"),
            ),
            construir=lambda p: GroupingMatcher(**p),
        ),
        # -- compras --------------------------------------------------------
        RegraDisponivel(
            nome="preferido",
            rotulo="Preferred supplier",
            categoria="DOMAIN",
            cost_class=CostClass.REGRA,
            # Igual a `FornecedorPreferido.describe().summary`, verbatim — ver
            # `test_resumo_da_REGRA_bate_com_o_describe_do_resolver`. Achado
            # revisando a Task 3: as duas frases tinham divergido (nenhum
            # teste comparava as duas antes dela restaurar a guarda).
            resumo="fornecedor preferido",
            construir=lambda p: FornecedorPreferido(),
        ),
        RegraDisponivel(
            nome="anteriores",
            rotulo="Past purchases",
            categoria="DOMAIN",
            cost_class=CostClass.REGRA,
            # Igual a `ComprasAnteriores.describe().summary`, verbatim —
            # mesmo motivo da entrada acima.
            resumo="compras anteriores",
            construir=lambda p: ComprasAnteriores(),
        ),
        # -- o degrau HUMANO que FECHA a cascata. Ver o docstring de `Catalogo`.
        RegraDisponivel(
            nome="revisor",
            rotulo="Approval",
            categoria="HUMAN",
            cost_class=CostClass.HUMANO,
            # Igual a `RevisorHumano.describe().summary`, verbatim — ver
            # `test_resumo_da_REGRA_bate_com_o_describe_do_resolver`. Mesma
            # classe de drift que `preferido`/`anteriores`, achada pela mesma
            # guarda restaurada.
            resumo="aplica as decisões aprovadas na fila de revisão",
            construir=_revisor_precisa_da_fila,
        ),
    ),
    agentes=(
        # -- conciliação ----------------------------------------------------
        AgenteDeclarado(
            name="investigador",
            system=_PROMPT_INVESTIGADOR,
            # `banco`, não `lancamento`: `lancamento` era o kind do domínio
            # antigo, renomeado para banco/contabil sem este bloco acompanhar.
            # Nenhuma fonte o produz, e o agente rodava sem ver item nenhum.
            # Um kind só, como todo `AgenteDeclarado`: ele parte de UM
            # lançamento bancário por tarefa e usa as ferramentas para ver o
            # lado contábil.
            kind="banco",
            # Os campos que `_campos` (asdict) expõe de um `BankEntry`. O
            # prompt antigo citava `{descricao}`, de uma `Divergence` que a
            # fonte não entrega, e levantaria KeyError no primeiro item.
            prompt=(
                "Lançamento bancário {id} de {date}: {description}. "
                "Valor {amount}, contraparte {counterparty}, documento {document}. "
                "Investigue a divergência com o lado contábil."
            ),
            tipos=(
                "DEFASAGEM_TEMPORAL",
                "DEVOLUCAO_FUNDOS",
                "PAGAMENTO_AGREGADO",
                "RETENCAO_IMPOSTO",
            ),
            abstem_com="NAO_IDENTIFICADO",
            ferramentas=catalogo_de_ferramentas().names(),
            max_turns=6,
        ),
        # -- engenharia de software -----------------------------------------
        #
        # O `swe` não traz regra nenhuma, e é deliberado: ele é o CASO
        # DEGENERADO do §1.3 do spec de composição — trabalho que começa direto
        # na classe AGENTE. Ele existe para provar que o kernel não supõe um
        # piso barato. É também onde o laço de promoção (§6.3 do spec da
        # plataforma) tem mais a ganhar: hoje 100% desse trabalho passa pelo
        # modelo.
        AgenteDeclarado(
            name="triador",
            system=PROMPT,
            kind=ISSUE,
            prompt="{titulo}\n\n{corpo}",
            # `NAO_SEI` fora de `tipos`: `DUVIDA` é um TIPO legítimo ("esta
            # issue é uma pergunta"), e confundir os dois custou 16 de 50 casos
            # fora do denominador da precisão (P6.86).
            tipos=("BUG", "FEATURE", "DUVIDA"),
            abstem_com="NAO_SEI",
            ferramentas=("contar_palavras",),
            max_turns=3,
        ),
        # -- compras --------------------------------------------------------
        AgenteDeclarado(
            name="buscador",
            system=_PROMPT_COMPRADOR,
            kind="requisicao",
            prompt="Requisição de {quantidade}x {item}",
            tipos=("FORNECEDOR_NOVO", "REQUISICAO_INVIABIL"),
            abstem_com="NAO_SEI",
            max_turns=3,
        ),
    ),
)
