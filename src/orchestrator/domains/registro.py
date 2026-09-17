"""Os domínios que a plataforma conhece.

**O que muda aqui.** Até este módulo, "o que dá para compor" era o `CATALOGO` do
grill — cinco resolvers de conciliação. A pergunta do dono foi direta: *"por que
só tem blocos de conciliação? eu quero uma plataforma geral."* Estava certo, e
havia seis resolvers escritos que o canvas não oferecia.

**A forma da generalidade, e por que ela não é uma lista maior.** Um domínio
declara quatro coisas:

    kinds        — que tipos de `WorkItem` ele trabalha
    ferramentas  — o CATÁLOGO delas (sem dados; `com_contexto` liga na execução)
    agentes      — declarações, que `construir_agente` valida construindo
    regras       — os blocos determinísticos, com os parâmetros ajustáveis

**Agente é DADO; regra é CÓDIGO com parâmetros expostos.** Casar por documento e
valor é lógica de domínio, e não há declaração que a substitua — fingir que há
produziria uma linguagem de regras pela metade. O que a composição escolhe é
QUAIS regras entram e com que parâmetros, nunca o corpo delas.

É a assimetria que faz a plataforma ser geral sem virar um gerador de código:
o caro (agente) é declarativo porque precisa ser composto por quem não programa;
o barato (regra) é código porque é onde a lógica do negócio realmente mora.

**Por que domínios não se misturam.** `L1` trabalha `kind="lancamento"`,
`FornecedorPreferido` trabalha `"requisicao"`, o triador trabalha `"issue"`. Uma
cascata com resolvers de dois domínios não é ruim — é vazia de sentido, porque o
segundo roda sobre um pool que o primeiro nem enxerga. `Dominio.kinds` é o que
torna isso verificável em vez de convenção.
"""

from dataclasses import dataclass

from orchestrator.agent.declarado import (
    AgenteDeclarado,
    ClienteDeValidacao,
    Dominio,
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
from orchestrator.review.fila import Fila
from orchestrator.review.revisor import RevisorHumano


@dataclass(frozen=True)
class Catalogo:
    """Tudo que dá para compor, junto, sem agrupamento.

    **Por que sem `kinds`.** O `Dominio` agrupava por `kind` porque "uma
    cascata com um resolver de conciliação e um de compras não é ruim — é
    vazia de sentido, porque o segundo roda sobre um pool que o primeiro nem
    enxerga". Continua verdade, e a fatia do grafo passou a dizer isso melhor:
    `Stage.consome`/`Stage.produz` declara a fiação POR DEGRAU e
    `WorkflowDefinition.__post_init__` recusa um grafo cujos kinds não
    conectam. Aquilo valida o grafo que vai rodar; isto validava uma partição
    de catálogo. O agrupamento é resto.

    **O `revisor` mora aqui, e o nome do tipo mente um pouco.** Ele é classe
    `HUMANO`, não regra. `RegraDisponivel` descreve "bloco determinístico com
    parâmetros ajustáveis", o que serve de forma, não de nome. Ele vivia só no
    catálogo do grill, e `Dominio` nenhum o carregava — a lacuna estava
    registrada em `App.tsx`. Fundir sem ele perderia o degrau que FECHA a
    cascata.
    """

    ferramentas: ToolRegistry
    regras: tuple[RegraDisponivel, ...] = ()
    agentes: tuple[AgenteDeclarado, ...] = ()

    def __post_init__(self) -> None:
        # Guarda 1, migrada de `Dominio.__post_init__` e mais perigosa aqui: a
        # composição indexa bloco por NOME, e dois iguais fariam a cascata
        # depender de quem foi procurado primeiro. Num catálogo plano a colisão
        # deixa de ser possível só dentro de um domínio.
        nomes = [r.nome for r in self.regras] + [a.name for a in self.agentes]
        repetidos = sorted({n for n in nomes if nomes.count(n) > 1})
        if repetidos:
            raise ValueError(f"catálogo com nome repetido entre blocos: {repetidos}")
        # Guarda 2, também migrada: VALIDAR É CONSTRUIR. Sem isto, uma
        # declaração inválida só falha ao EXECUTAR — depois de a pessoa ter
        # montado a cascata inteira e clicado em rodar.
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

# --------------------------------------------------------------------------
# Conciliação — a implementação de referência (§1.3)
# --------------------------------------------------------------------------

_PROMPT_INVESTIGADOR = """Você investiga divergências de conciliação bancária.

Responda APENAS com um objeto JSON:
{"tipo": <um dos tipos>, "explicacao": <texto curto>,
 "evidencia": [<strings>], "confianca": "ALTA"|"MEDIA"|"BAIXA"}

Use as ferramentas para buscar o que falta. Não saber é resposta válida:
responda NAO_IDENTIFICADO com confiança BAIXA."""

CONCILIACAO = Dominio(
    id="conciliacao",
    nome="Conciliação bancária",
    kinds=("lancamento",),
    ferramentas=catalogo_de_ferramentas(),
    regras=(
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
    ),
    agentes=(
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
    ),
)

# --------------------------------------------------------------------------
# Engenharia de software
# --------------------------------------------------------------------------

SWE = Dominio(
    id="swe",
    nome="Triagem de issues",
    kinds=(ISSUE,),
    ferramentas=ferramentas_swe(),
    # SEM regras, e é deliberado: o `swe` é o CASO DEGENERADO do §1.3 do spec de
    # composição — uma cascata que começa direto na classe AGENTE. Ele existe
    # para provar que o kernel não supõe que todo domínio tenha um piso barato.
    #
    # É também o domínio onde o laço de promoção (§6.3 do spec da plataforma)
    # tem mais a ganhar: hoje 100% do trabalho dele passa pelo modelo.
    regras=(),
    agentes=(
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
    ),
)

# --------------------------------------------------------------------------
# Compras
# --------------------------------------------------------------------------

_PROMPT_COMPRADOR = """Você procura fornecedor para uma requisição de compra.

Responda APENAS com um objeto JSON:
{"tipo": "FORNECEDOR_NOVO"|"REQUISICAO_INVIABIL"|"NAO_SEI",
 "explicacao": <texto curto>, "evidencia": [<strings>],
 "confianca": "ALTA"|"MEDIA"|"BAIXA"}

Não saber é resposta válida: responda NAO_SEI com confiança BAIXA."""

PROCUREMENT = Dominio(
    id="procurement",
    nome="Compras",
    kinds=("requisicao", "fornecedor"),
    # Sem ferramentas ainda: o domínio é esqueleto, e um registro vazio DIZ
    # isso. Inventar ferramentas para preencher a tela seria pior que a lacuna.
    ferramentas=ToolRegistry(contexto=None),
    regras=(
        RegraDisponivel(
            nome="preferido",
            cost_class=CostClass.REGRA,
            resumo="fornecedor preferido que atende o item",
            construir=lambda p: FornecedorPreferido(),
        ),
        RegraDisponivel(
            nome="anteriores",
            cost_class=CostClass.REGRA,
            resumo="qualquer fornecedor que já atendeu este item antes",
            construir=lambda p: ComprasAnteriores(),
        ),
    ),
    agentes=(
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


# --------------------------------------------------------------------------
# Redação — roda, mas não entra em `DOMINIOS`. Ver a nota abaixo.
# --------------------------------------------------------------------------
#
# `domains/redacao/workflow.py` existe e é executável (`definition(cliente)` +
# `pool(...)`, exercitado por `tests/domains/test_redacao.py`). O que falta AQUI
# não é escrevê-lo — é catalogá-lo: os três degraus são `Tarefa`, que
# TRANSFORMA um item no próximo (produz um `kind` novo por degrau, ao contrário
# de julgar o item que recebeu). Nem `AgenteDeclarado` nem `RegraDisponivel`
# sabem descrever isso — os dois descrevem um resolver que decide sobre UM
# item e devolve `Proposal`/`Resolution` a respeito DELE, nunca um item de
# outro `kind` para o próximo degrau consumir. Forçar `redacao` num
# `AgenteDeclarado` mentiria sobre o que ele faz; e um `Dominio` com
# `agentes=()` e `regras=()` seria um item de catálogo vazio, o que
# `test_os_TRES_dominios_se_declaram` (fixo em EXATAMENTE três, sem editar)
# recusa por bom motivo — cardápio maior não é o mesmo que plataforma mais
# geral se o item novo não compõe nada de verdade.
#
# Ensinar `AgenteDeclarado` a declarar `produz` é exatamente o X7/X8 que o
# plano de execução-como-grafo deixa de propósito para depois de `redacao`
# existir como esqueleto executável — ver a nota de frição em
# `tests/domains/test_generalidade.py` e a entrada correspondente em
# `docs/superpowers/DECISOES.md`.


DOMINIOS: dict[str, Dominio] = {d.id: d for d in (CONCILIACAO, SWE, PROCUREMENT)}


def dominio(id: str) -> Dominio:
    if id not in DOMINIOS:
        raise KeyError(f"domínio desconhecido: {id!r}. disponíveis: {sorted(DOMINIOS)}")
    return DOMINIOS[id]


def _todas_as_ferramentas() -> ToolRegistry:
    """Um registro com as ferramentas de todas as origens.

    `register` já recusa nome repetido, então uma colisão entre origens falha
    na importação em vez de uma das duas ganhar em silêncio. `contexto=None`
    porque catálogo NÃO executa: quem executa chama `com_contexto`.
    """
    junto = ToolRegistry(contexto=None)
    for origem in (catalogo_de_ferramentas(), ferramentas_swe()):
        for nome in origem.names():
            junto.register(origem.spec(nome))
    return junto


# O revisor: o degrau HUMANO que fecha a cascata. Ver o docstring de `Catalogo`.
_REVISOR = RegraDisponivel(
    nome="revisor",
    cost_class=CostClass.HUMANO,
    resumo="a decisão humana que fecha a cascata",
    construir=lambda p: RevisorHumano(fila=Fila.vazia()),
)

CATALOGO = Catalogo(
    ferramentas=_todas_as_ferramentas(),
    regras=(*CONCILIACAO.regras, *PROCUREMENT.regras, _REVISOR),
    agentes=(*CONCILIACAO.agentes, *SWE.agentes, *PROCUREMENT.agentes),
)
