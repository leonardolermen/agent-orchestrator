"""O modelo de rastro: `Span` e a árvore de uma execução.

`TraceEvent` já existia, e é o rastro de UMA investigação — plano, dentro de uma
`Proposal`. Ele responde "o que aconteceu com este item". Não responde "o que
aconteceu nesta execução": não tem pai, não tem duração, não cobre resolver de
regra nem decisão de política, e não existe fora de uma proposta.

`Span` é o que responde. Tem pai, tem início e fim, cobre TODO resolver, e
carrega custo — de modo que a soma dos filhos é o custo do pai, por construção.

**Por que um modelo próprio e não OpenTelemetry** (ADR-08): custo em
micro-centavos `int` não tem lugar canônico em OTel e viraria atributo float —
ponto flutuante em dinheiro é proibido aqui. E `status="abstencao"` e
`status="pulado"` não são OK nem ERROR: são desfechos legítimos que o produto
precisa contar separadamente. OTel entra como EXPORTADOR, mão única.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from orchestrator.kernel.cost import Cost


class SpanKind(StrEnum):
    RUN = "run"
    STAGE = "stage"
    POLICY = "policy"
    RESOLVER = "resolver"
    ITEM = "item"
    LLM = "llm"
    TOOL = "tool"
    GAP = "gap"


class SpanStatus(StrEnum):
    """`abstencao` e `pulado` NÃO são erro.

    São desfechos legítimos e comercialmente distintos: abstenção é o agente
    dizendo "não sei" (que custou dinheiro), e pulado é a política dizendo "não
    vale a pena" (que economizou). Colapsá-los em ERROR perderia exatamente a
    distinção que o produto vende.
    """

    OK = "ok"
    ERRO = "erro"
    ABSTENCAO = "abstencao"
    PULADO = "pulado"


@dataclass(frozen=True)
class Span:
    id: str
    parent_id: str | None
    kind: SpanKind
    name: str
    status: SpanStatus = SpanStatus.OK
    started_at: datetime | None = None
    duration_ms: int = 0
    cost: Cost = field(default_factory=Cost.zero)
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class Trace:
    """A árvore de uma execução. Lista plana mais os pais — a árvore é derivada.

    Lista plana porque é o que persiste bem (uma linha por span, append-only,
    mesmo formato da fila e do run store) e porque a árvore é reconstruível sem
    ambiguidade. Guardar a árvore aninhada obrigaria a serializar recursão e
    tornaria impossível escrever um span antes do pai terminar.
    """

    run_id: str
    spans: tuple[Span, ...] = ()

    def raiz(self) -> Span | None:
        return next((s for s in self.spans if s.parent_id is None), None)

    def filhos(self, span_id: str) -> tuple[Span, ...]:
        return tuple(s for s in self.spans if s.parent_id == span_id)

    def por_kind(self, kind: SpanKind) -> tuple[Span, ...]:
        return tuple(s for s in self.spans if s.kind is kind)

    def custo_total(self, model: str) -> int:
        """Soma os spans FOLHA, nunca a árvore inteira.

        Somar todos os spans contaria cada token duas vezes — uma no span de
        LLM e outra no `resolver` que o contém. Custo de pai é agregação dos
        filhos, e agregar a agregação é o erro clássico desta estrutura.
        """
        folhas = {s.id for s in self.spans} - {
            s.parent_id for s in self.spans if s.parent_id
        }
        return sum(
            s.cost.microcents(model) if s.cost != Cost.zero() else 0
            for s in self.spans
            if s.id in folhas
        )
