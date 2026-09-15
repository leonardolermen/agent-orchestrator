"""Contratos de saída do agente investigador.

O agente nunca devolve texto livre. Ele devolve uma proposta estruturada, com
evidência citada e confiança declarada — ou uma abstenção, que é resposta
válida e deve ser barata.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from orchestrator.taxonomy import DivergenceType


class Confidence(StrEnum):
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"


# Preço por token em micro-cents de USD (1 micro-cent = 1e-6 de centavo de
# dólar). Inteiro de propósito: a constraint de dinheiro do projeto vale aqui
# também, e ponto flutuante acumulando por divergência erraria devagar.
#
# Fonte: tabela de preços da API por 1M de tokens.
#   opus-5     $5,00 entrada / $25,00 saída
#   sonnet-5   $2,00 / $10,00
#   haiku-4.5  $1,00 / $5,00
#
# Ler do cache custa ~10% da entrada. ESCREVER no cache custa ~125% — e esses
# tokens de escrita não aparecem nem em input_tokens nem em cached_tokens na
# resposta da API. Ignorá-los subcontaria o custo real em toda primeira chamada
# de cada janela de cache, e custo por divergência é o número comercial deste
# produto.
#
# Ordem: entrada, saída, leitura de cache, escrita de cache.
_PRECOS = {
    "claude-opus-5": (500, 2500, 50, 625),
    "claude-sonnet-5": (200, 1000, 20, 250),
    "claude-haiku-4-5": (100, 500, 10, 125),
}


@dataclass(frozen=True)
class Cost:
    """O que uma investigação consumiu. Tokens, não dinheiro — o preço depende
    do modelo, e o mesmo consumo custa diferente em cada um."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0
    calls: int = 0

    @staticmethod
    def zero() -> "Cost":
        return Cost()

    def __add__(self, outro: "Cost") -> "Cost":
        return Cost(
            input_tokens=self.input_tokens + outro.input_tokens,
            output_tokens=self.output_tokens + outro.output_tokens,
            cached_tokens=self.cached_tokens + outro.cached_tokens,
            cache_creation_tokens=self.cache_creation_tokens
            + outro.cache_creation_tokens,
            calls=self.calls + outro.calls,
        )

    def microcents(self, model: str) -> int:
        """Custo em micro-cents de USD para o modelo dado."""
        if model not in _PRECOS:
            raise ValueError(f"modelo sem preço conhecido: {model!r}")
        entrada, saida, leitura, escrita = _PRECOS[model]
        return (
            self.input_tokens * entrada
            + self.output_tokens * saida
            + self.cached_tokens * leitura
            + self.cache_creation_tokens * escrita
        )


def modelo_precificado(model: str) -> bool:
    """Verdadeiro quando o modelo tem preço conhecido na tabela.

    Fronteira pública para código fora deste módulo (ex.: `AnthropicClient`)
    que precisa validar um modelo sem importar a tabela de preços privada
    diretamente.
    """
    return model in _PRECOS


class TraceKind(StrEnum):
    """Os cinco tipos de passo que aparecem no rastro de uma investigação."""

    ENTRADA = "entrada"
    ERRO = "erro"
    LLM = "llm"
    TOOL = "tool"
    OUTCOME = "outcome"


@dataclass(frozen=True)
class TraceEvent:
    """Um passo do que aconteceu ao investigar uma divergência.

    O spec seção 7 exige poder reconstruir por que o sistema chegou a uma
    conclusão. Num produto que um contador vai auditar, uma proposta sem
    rastro é uma afirmação sem fonte.
    """

    kind: TraceKind
    detail: dict[str, Any]


@dataclass(frozen=True)
class Proposal:
    """O que o agente propõe para uma divergência.

    Uma proposta NÃO resolve a divergência. Ela explica e sugere; quem resolve
    é o humano ao aprovar.
    """

    divergence_id: str
    tipo: DivergenceType
    explicacao: str
    evidencia: list[str]
    confianca: Confidence
    acao_sugerida: str
    cost: Cost = field(default_factory=Cost.zero)
    trace: list[TraceEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Coage os dois enums antes de qualquer verificação. O projeto compara
        # por identidade em toda parte (`p.tipo is DivergenceType.X`), e uma
        # string crua vinda de JSON desserializado passaria batido por todas
        # elas — inclusive pelo guard de evidência logo abaixo. Coagir uma vez
        # aqui torna Proposal seguro de construir a partir de dado externo.
        object.__setattr__(self, "tipo", DivergenceType(self.tipo))
        object.__setattr__(self, "confianca", Confidence(self.confianca))

        # Confiança alta sem evidência é a combinação que destrói a
        # credibilidade do produto mais rápido que qualquer erro.
        if self.confianca is Confidence.ALTA and not self.evidencia:
            raise ValueError(
                f"proposta {self.divergence_id} declara confiança alta sem evidência"
            )

    @staticmethod
    def abstencao(
        divergence_id: str,
        motivo: str,
        cost: Cost | None = None,
        trace: list[TraceEvent] | None = None,
    ) -> "Proposal":
        """Não saber é resposta válida, e precisa ser barata de produzir."""
        return Proposal(
            divergence_id=divergence_id,
            tipo=DivergenceType.NAO_IDENTIFICADO,
            explicacao=motivo,
            evidencia=[],
            confianca=Confidence.BAIXA,
            acao_sugerida="investigar_manual",
            cost=cost or Cost.zero(),
            trace=trace or [],
        )


@dataclass(frozen=True)
class InvestigationOutput:
    """Tudo que uma passada do investigador produziu."""

    proposals: list[Proposal]
    cost: Cost
