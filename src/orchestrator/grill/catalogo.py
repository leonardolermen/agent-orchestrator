"""O catálogo: a tabela única de resolvers proponíveis.

O `enum` do schema da ferramenta e o construtor usado pela validação saem
DAQUI, da mesma estrutura. Um resolver que o grill consegue propor é, por
construção, um resolver que o motor consegue rodar — não porque alguém valida,
mas porque não há de onde vir. Duas listas paralelas (uma no schema, outra no
construtor) seriam o join frágil que P3.2 já custou uma correção.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from orchestrator.agent.investigator import Investigator
from orchestrator.agent.llm import LLMClient, LLMResponse
from orchestrator.agent.tools import ToolContext
from orchestrator.kernel.cost import CostClass
from orchestrator.matching.exact import ExactMatcher
from orchestrator.matching.grouping import GroupingMatcher
from orchestrator.matching.tolerance import ToleranceMatcher
from orchestrator.review.fila import Fila
from orchestrator.review.revisor import RevisorHumano
from orchestrator.workflow.resolver import Resolver

# Um modelo REAL da tabela de preços, de propósito: `Investigator.__post_init__`
# chama `Cost.zero().microcents(self.client.model)` e um nome inventado faria a
# construção levantar — o que impediria até de DESENHAR um workflow com agente.
MODELO_INERTE = "claude-opus-5"


class ClienteAusente:
    """`LLMClient` sentinela: existe para ser construído, nunca para ser chamado.

    É o que permite à API construir e desenhar um resolver pago sem que exista
    caminho de execução paga atrás de um endpoint. O 409 do `app.py` é a porta
    educada; isto aqui é a tranca.
    """

    model: str = MODELO_INERTE

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        raise RuntimeError(
            "ClienteAusente.complete() foi chamado: algum caminho de execução "
            "chegou ao modelo por onde não deveria existir caminho nenhum"
        )


@dataclass(frozen=True)
class ParametroSpec:
    """O que o modelo pode propor para um resolver. DESCREVE, não valida.

    Não carrega faixa (mínimo/máximo) de propósito: as restrições já vivem nos
    `__post_init__` dos resolvers, e duplicá-las aqui criaria duas fontes de
    verdade que divergiriam na primeira mudança. Ver §3.2 do spec.
    """

    nome: str
    default: int
    descricao: str


@dataclass(frozen=True)
class EntradaCatalogo:
    nome: str
    cost_class: CostClass
    resumo: str
    parametros: tuple[ParametroSpec, ...]
    # Assinatura UNIFORME em todas as entradas, mesmo nas que ignoram quase
    # tudo: `construir(parametros, *, fila, cliente, context)`. Assinaturas
    # variáveis exigiriam introspecção para saber o que passar — e é
    # exatamente esse padrão que já nos deu um defeito silencioso no
    # `_construir_definicao` da API.
    construir: Callable[..., Resolver]


def _param(cls: type, nome: str, descricao: str) -> ParametroSpec:
    """Lê o default do PRÓPRIO resolver. Renomear o campo lá explode aqui, no
    import — alto, e não em silêncio com um default falso na tela."""
    campos = {f.name: f for f in dataclasses.fields(cls)}
    if nome not in campos:
        raise ValueError(f"{cls.__name__} não tem campo {nome!r}")
    return ParametroSpec(nome=nome, default=campos[nome].default, descricao=descricao)


def _l1(p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext) -> Resolver:
    return ExactMatcher()


def _l2(p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext) -> Resolver:
    return ToleranceMatcher(**p)


def _l3(p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext) -> Resolver:
    return GroupingMatcher(**p)


def _agente(
    p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext
) -> Resolver:
    return Investigator(client=cliente, context=context, fila=fila, **p)


def _revisor(
    p: dict[str, int], *, fila: Fila, cliente: LLMClient, context: ToolContext
) -> Resolver:
    return RevisorHumano(fila=fila)


CATALOGO: dict[str, EntradaCatalogo] = {
    "L1": EntradaCatalogo(
        nome="L1",
        cost_class=CostClass.REGRA,
        resumo="documento, valor e data coincidem exatamente",
        parametros=(),
        construir=_l1,
    ),
    "L2": EntradaCatalogo(
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
        construir=_l2,
    ),
    "L3": EntradaCatalogo(
        nome="L3",
        cost_class=CostClass.REGRA,
        resumo="um lançamento bancário cobrindo N contábeis do mesmo fornecedor",
        parametros=(
            _param(
                GroupingMatcher,
                "max_group_size",
                "quantos lançamentos contábeis um pagamento pode cobrir",
            ),
            _param(
                GroupingMatcher,
                "max_business_days",
                "janela de data do grupo, em dias úteis",
            ),
            _param(
                GroupingMatcher,
                "max_candidates",
                "teto de candidatos considerados; protege contra busca exponencial",
            ),
        ),
        construir=_l3,
    ),
    "agente": EntradaCatalogo(
        nome="agente",
        cost_class=CostClass.AGENTE,
        resumo="investiga o que as regras não resolveram e propõe uma explicação",
        parametros=(
            _param(Investigator, "max_turns", "turnos por divergência investigada"),
            _param(
                Investigator,
                "budget_microcents",
                "teto de gasto POR divergência, em micro-centavos de dólar",
            ),
            _param(
                Investigator,
                "budget_total_microcents",
                "teto de gasto da execução inteira, em micro-centavos de dólar",
            ),
        ),
        construir=_agente,
    ),
    "revisor": EntradaCatalogo(
        nome="revisor",
        cost_class=CostClass.HUMANO,
        resumo="aplica as decisões aprovadas na fila de revisão",
        parametros=(),
        construir=_revisor,
    ),
}
