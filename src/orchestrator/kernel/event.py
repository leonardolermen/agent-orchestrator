"""O que aconteceu durante uma execução, como stream tipado.

**Eventos observam; não controlam.** O motor não reage a evento nenhum para
decidir o que fazer em seguida — ver ADR-02. Com controle movido a eventos, a
ordem de execução deixa de ser propriedade da definição e passa a ser
emergente, e o golden de 12 sementes, o `85.3%` travado no CI e o
`ReplayResume` todos dependem de determinismo.

O que os eventos dão é o que falta: observabilidade (PR #12+), fila de revisão
alimentada por assinatura, e colheita de caso de avaliação (M6) — tudo como
ASSINANTE, sem uma linha a mais no motor.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EventKind(StrEnum):
    RUN_INICIADO = "run.iniciado"
    RUN_CONCLUIDO = "run.concluido"
    RUN_FALHOU = "run.falhou"
    STAGE_INICIADO = "stage.iniciado"
    RESOLVER_INICIADO = "resolver.iniciado"
    RESOLVER_CONCLUIDO = "resolver.concluido"
    ITEM_RESOLVIDO = "item.resolvido"
    ITEM_PROPOSTO = "item.proposto"
    ERRO = "erro"


@dataclass(frozen=True)
class Event:
    kind: EventKind
    run_id: str
    at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Event], None]


class EventBus:
    """Síncrono e em processo. Nenhuma fila, nenhum broker — ADR-14.

    Um assinante que levanta NÃO derruba a execução: o erro vai para stderr e o
    laço continua. É a mesma política de `listar_receitas`, e pela mesma razão —
    um observador quebrado não pode custar um fechamento. O preço é que um bug
    de assinante fica quieto, e por isso ele vai para stderr em vez de sumir.
    """

    def __init__(self) -> None:
        self._por_tipo: dict[EventKind, list[Handler]] = {}
        self._todos: list[Handler] = []

    def subscribe(self, kind: EventKind | None, handler: Handler) -> None:
        """`kind=None` assina tudo — é o que o coletor de spans (M4) usa."""
        if kind is None:
            self._todos.append(handler)
        else:
            self._por_tipo.setdefault(kind, []).append(handler)

    def emit(self, event: Event) -> None:
        for h in (*self._todos, *self._por_tipo.get(event.kind, ())):
            try:
                h(event)
            except Exception as erro:  # noqa: BLE001
                # Captura LARGA, e aqui ela é o requisito: observação não pode
                # derrubar execução. A inversão em relação à captura estreita
                # de `client.complete()` é a mesma que `Investigator` já
                # documenta entre o laço e a execução de ferramenta.
                print(
                    f"assinante de {event.kind} falhou: {erro!r}",
                    file=sys.stderr,
                )


class NullBus(EventBus):
    """Não emite nada. O default do motor.

    Existe para que `execute()` não precise de `if bus is not None` em cada
    ponto de emissão, e para que desligar observabilidade seja trocar um objeto
    em vez de mudar o laço.
    """

    def emit(self, event: Event) -> None:
        return
