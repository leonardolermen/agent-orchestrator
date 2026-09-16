"""Contratos de saída do agente investigador.

O agente nunca devolve texto livre. Ele devolve uma proposta estruturada, com
evidência citada e confiança declarada — ou uma abstenção, que é resposta
válida e deve ser barata.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from orchestrator.kernel.cost import Cost
from orchestrator.taxonomy import DivergenceType


class Confidence(StrEnum):
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"



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
