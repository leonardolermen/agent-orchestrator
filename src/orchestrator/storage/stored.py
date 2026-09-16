"""O resumo de um `Run`, que é o que de fato cabe em disco.

Um `Run` carrega o `WorkSet` que sobrou, e o `WorkSet` carrega payloads do
DOMÍNIO — dataclasses que o kernel nunca inspeciona e que ele, portanto, não
sabe serializar. Persistir um `Run` inteiro exigiria que o storage conhecesse
todo domínio, que é exatamente a dependência que a arquitetura proíbe.

Então o store guarda o resumo: identidade, estado, tempo, custo e contagens. É
o que a listagem de runs e a tela de custo precisam.

Reconstruir a execução inteira é outro problema, e tem outra solução: `Source`
+ `input_ref` (PR #9) tornam a ENTRADA reproduzível, e `ReplayResume` (M7)
reexecuta em vez de desserializar. Ver §12.5 do spec — para trabalho de escala
de minutos, replay é estritamente melhor que checkpoint: não há estado
serializado para corromper nem versão de snapshot para migrar.
"""

from dataclasses import dataclass, field
from datetime import datetime

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.run import Run, RunState


@dataclass(frozen=True)
class StoredRun:
    id: str
    workflow_id: str
    workflow_version: str
    state: RunState
    started_at: datetime
    finished_at: datetime | None
    input_ref: str
    duration_ms: int | None
    resolved: int
    proposed: int
    unresolved: int
    cost_by_resolver: dict[str, Cost] = field(default_factory=dict)
    resolved_by_resolver: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    @staticmethod
    def of(run: Run) -> "StoredRun":
        return StoredRun(
            id=run.id,
            workflow_id=run.workflow_id,
            workflow_version=run.workflow_version,
            state=run.state,
            started_at=run.started_at,
            finished_at=run.finished_at,
            input_ref=run.input_ref,
            duration_ms=run.duration_ms,
            resolved=len(run.resolutions),
            proposed=len(run.proposals),
            unresolved=len(run.unresolved.items),
            cost_by_resolver=dict(run.cost_by_resolver),
            resolved_by_resolver=dict(run.resolved_by_resolver),
            error=run.error,
        )
