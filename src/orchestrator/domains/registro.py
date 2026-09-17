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
from typing import NoReturn

from orchestrator.agent.declarado import (
    AgenteDeclarado,
    ClienteDeValidacao,
    ParametroDeRegra,
    RegraDisponivel,
    construir_agente,
)
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.conciliacao.ferramentas import catalogo_de_ferramentas
from orchestrator.domains.procurement.workflow import (
    ComprasAnteriores,
    FornecedorPreferido,
)
from orchestrator.domains.swe.workflow import ISSUE, PROMPT
from orchestrator.domains.swe.workflow import ferramentas as ferramentas_swe
from orchestrator.kernel.cost import CostClass
from orchestrator.matching.exact import ExactMatcher
from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.matching.tolerance import ToleranceMatcher


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
    parâmetro que o construtor não aceita. Mesma técnica de `grill.catalogo._param`.
    """
    import dataclasses

    campos = {f.name: f for f in dataclasses.fields(cls)}
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


def _revisor_precisa_da_fila(parametros: dict[str, int]) -> NoReturn:
    """`revisor` não constrói por esta via — e é ERRO, não decoração.

    `RegraDisponivel.construir` tem assinatura uniforme `(parametros) ->
    Resolver` (ver o docstring da classe), sem onde receber a fila REAL de
    decisões já tomadas. Um `RevisorHumano(fila=Fila.vazia())` aqui
    CONSTRUIRIA — pareceria funcionar, a cascata ficaria "desenhável" — e
    decisões aprovadas nunca chegariam à execução, sem nada avisar: o
    fallback silencioso que o spec proíbe, só que plausível. Achado revisando
    a Task 3 (`docs/superpowers/sdd/2026-09-17-quadro-em-branco/`): o único
    motivo de ele não ter mordido ainda é `grill.receita.construir` desviar
    deste `construir` olhando `cost_class`. Um segundo consumidor que não
    soubesse disso — `construir_composicao`, por exemplo — receberia fila
    vazia em silêncio.

    Quem compõe uma cascata com um bloco `CostClass.HUMANO` precisa
    reconhecer a classe e montar o resolver direto, com a fila de verdade —
    exatamente como `grill.receita.construir` faz.
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
# `AgenteDeclarado` a declarar `produz` é o X7/X8 que o plano de
# execução-como-grafo reserva para depois — ver a nota de fricção em
# `tests/domains/test_generalidade.py` e a entrada em
# `docs/superpowers/DECISOES.md`.
# ---------------------------------------------------------------------------

CATALOGO = Catalogo(
    ferramentas=_todas_as_ferramentas(),
    regras=(
        # -- conciliação: a implementação de referência (§1.3) --------------
        RegraDisponivel(
            nome="L1",
            cost_class=CostClass.REGRA,
            resumo="documento, valor e data coincidem exatamente",
            construir=lambda p: ExactMatcher(),
        ),
        RegraDisponivel(
            nome="L2",
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
            cost_class=CostClass.REGRA,
            # Igual a `ComprasAnteriores.describe().summary`, verbatim —
            # mesmo motivo da entrada acima.
            resumo="compras anteriores",
            construir=lambda p: ComprasAnteriores(),
        ),
        # -- o degrau HUMANO que FECHA a cascata. Ver o docstring de `Catalogo`.
        RegraDisponivel(
            nome="revisor",
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
            kind="lancamento",
            prompt="Divergência {id}: {descricao}",
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
