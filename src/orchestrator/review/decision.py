"""O que um humano afirma sobre uma divergência.

Uma `Proposal` explica e sugere; ela nunca resolve. Uma `Decision` é o único
caminho humano até um `MatchResult` — é ela que tira o item do pool.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from orchestrator.taxonomy import DivergenceType

_PREFIXO = "conciliar_com("


class Veredito(StrEnum):
    ACEITAR = "aceitar"
    REJEITAR = "rejeitar"
    CORRIGIR = "corrigir"


def ids_de_conciliar_com(acao: str) -> frozenset[str]:
    """Extrai os ids de `conciliar_com(a, b)`.

    Até agora `acao_sugerida` só era validada por `startswith`: bastava para
    despachar, não para aplicar. Aceitar uma proposta precisa dos ids de
    verdade.

    Qualquer forma que não seja exatamente essa devolve vazio — inclusive
    `ajustar(...)` e `investigar_manual`, que são ações válidas que não
    conciliam nada. Vazio não é erro aqui; é "esta decisão não casa ninguém".
    """
    texto = acao.strip()
    if not texto.startswith(_PREFIXO) or not texto.endswith(")"):
        return frozenset()
    dentro = texto[len(_PREFIXO) : -1]
    return frozenset(p.strip() for p in dentro.split(",") if p.strip())


@dataclass(frozen=True)
class Decision:
    divergence_id: str
    veredito: Veredito
    tipo: DivergenceType | None
    conciliar_com: frozenset[str]
    autor: str
    quando: datetime
    motivo: str = ""

    def __post_init__(self) -> None:
        if self.veredito is Veredito.CORRIGIR and self.tipo is None:
            raise ValueError(
                "corrigir exige `tipo`: é o que o humano afirma no lugar do "
                "que o agente propôs"
            )
        if self.quando.tzinfo is None:
            raise ValueError(
                "`quando` precisa de fuso (use UTC): horário ingênuo não é um "
                "instante, e a trilha de auditoria depende de ordem"
            )

    @property
    def concilia(self) -> bool:
        """Verdadeiro quando esta decisão deve virar um match."""
        return self.veredito is not Veredito.REJEITAR and bool(self.conciliar_com)
