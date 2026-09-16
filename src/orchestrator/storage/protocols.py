"""As fronteiras de persistência. Protocolos, não implementações.

Uma só implementação existe hoje (JSONL append-only), e é a mesma escolha que a
`Fila` já fez — o docstring dela explica por quê: append-only não é economia de
esforço, é a trilha de auditoria saindo como subproduto do formato em vez de
como funcionalidade construída depois.

O protocolo existe para que o dia de trocar por SQLite não seja o dia de
reescrever quem lê. O gatilho está no ADR-05 e é concreto: >10k runs ou
listagem acima de ~500ms — não "SQLite é mais sério".
"""

from typing import Protocol

from orchestrator.kernel.run import Run, RunState
from orchestrator.storage.stored import StoredRun


class RunStore(Protocol):
    def save(self, run: Run) -> None: ...

    def get(self, run_id: str) -> StoredRun | None: ...

    def list(
        self,
        *,
        workflow_id: str | None = None,
        state: RunState | None = None,
        limit: int = 50,
    ) -> list[StoredRun]:
        """Mais recentes primeiro.

        A ordenação sai de graça do formato do id (`new_run_id` é ordenável por
        tempo), sem índice e sem coluna de ordenação.
        """
        ...
