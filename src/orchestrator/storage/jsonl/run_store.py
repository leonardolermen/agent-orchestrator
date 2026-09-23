"""`RunStore` em JSONL append-only.

Mesma escolha de formato e o mesmo motivo da `Fila`: append-only entrega
trilha de auditoria como subproduto, é diffável, e não custa dependência
nenhuma. Ver ADR-05.

Substitui o `@lru_cache(maxsize=64)` de `api/app.py`, que era um run store
disfarçado de memoização — e cujo próprio docstring admitia que a função tinha
deixado de ser pura e que por isso o POST de decisão precisava chamar
`cache_clear()`. Um store não invalida errado, porque não finge ser cache.
"""

import json
from datetime import datetime
from pathlib import Path

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.run import Run, RunState
from orchestrator.storage.stored import StoredRun


def _para_dict(s: StoredRun) -> dict:
    return {
        "id": s.id,
        "workflow_id": s.workflow_id,
        "workflow_version": s.workflow_version,
        "state": s.state.value,
        "started_at": s.started_at.isoformat(),
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "input_ref": s.input_ref,
        "duration_ms": s.duration_ms,
        "resolved": s.resolved,
        "proposed": s.proposed,
        "unresolved": s.unresolved,
        # Os CINCO campos de Cost, como em `review/serial.py` e `eval/replay.py`.
        # Perder um faz o store reportar custo menor que o real — o mesmo
        # defeito que P2.15 corrigiu uma vez e que só reaparece por descuido de
        # serialização campo a campo.
        "cost_by_resolver": {
            nome: {
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "cached_tokens": c.cached_tokens,
                "cache_creation_tokens": c.cache_creation_tokens,
                "calls": c.calls,
            }
            for nome, c in sorted(s.cost_by_resolver.items())
        },
        "modelo_por_resolver": dict(sorted(s.modelo_por_resolver.items())),
        "resolved_by_resolver": dict(sorted(s.resolved_by_resolver.items())),
        "error": s.error,
    }


def _de_dict(d: dict) -> StoredRun:
    return StoredRun(
        id=d["id"],
        workflow_id=d["workflow_id"],
        workflow_version=d["workflow_version"],
        state=RunState(d["state"]),
        started_at=datetime.fromisoformat(d["started_at"]),
        finished_at=(
            datetime.fromisoformat(d["finished_at"]) if d["finished_at"] else None
        ),
        input_ref=d["input_ref"],
        duration_ms=d["duration_ms"],
        resolved=d["resolved"],
        proposed=d["proposed"],
        unresolved=d["unresolved"],
        cost_by_resolver={n: Cost(**c) for n, c in d["cost_by_resolver"].items()},
        # `.get` e nao `[]`: as linhas gravadas antes deste campo continuam
        # legiveis, e um resolver sem modelo cai no default de quem le — que
        # e exatamente com o que elas foram precificadas na epoca.
        modelo_por_resolver=dict(d.get("modelo_por_resolver", {})),
        resolved_by_resolver=dict(d["resolved_by_resolver"]),
        error=d.get("error"),
    )


class JsonlRunStore:
    """Um arquivo, uma linha por run. Sem lock.

    Uma máquina, um usuário, `open("a")` por linha é seguro o bastante — a
    mesma premissa que `Fila` documenta, e o mesmo gatilho para revê-la: um
    segundo escritor.
    """

    def __init__(self, caminho: Path) -> None:
        self._caminho = Path(caminho)

    def save(self, run: Run) -> None:
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        linha = json.dumps(_para_dict(StoredRun.of(run)), ensure_ascii=False)
        with self._caminho.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")

    def _todos(self) -> list[StoredRun]:
        if not self._caminho.exists():
            return []
        achados = []
        texto = self._caminho.read_text(encoding="utf-8")
        for numero, linha in enumerate(texto.splitlines(), start=1):
            if not linha.strip():
                continue
            try:
                achados.append(_de_dict(json.loads(linha)))
            except Exception as erro:
                # Mesma disciplina da `Fila`: um registro ruim não some em
                # silêncio, e a mensagem diz QUAL registro — quem lê isso é
                # alguém investigando um run que sumiu, não um dev com o
                # traceback do parser na cabeça.
                raise ValueError(
                    f"registro inválido em {self._caminho} na linha {numero}: {erro}"
                ) from erro
        return achados

    def get(self, run_id: str) -> StoredRun | None:
        # ÚLTIMA vence: um run pode ser salvo de novo (resume, M7), e o estado
        # é o mais recente. O log guarda todos — é ele a auditoria. Mesma
        # semântica que `Fila` aplica a decisão.
        achado = None
        for s in self._todos():
            if s.id == run_id:
                achado = s
        return achado

    def list(
        self,
        *,
        workflow_id: str | None = None,
        state: RunState | None = None,
        limit: int = 50,
    ) -> list[StoredRun]:
        por_id: dict[str, StoredRun] = {}
        for s in self._todos():
            por_id[s.id] = s
        achados = [
            s
            for s in por_id.values()
            if (workflow_id is None or s.workflow_id == workflow_id)
            and (state is None or s.state is state)
        ]
        # Ordena pelo ID, não por `started_at`: `new_run_id` é ordenável por
        # tempo, e ordenar por string é estável entre runs do mesmo
        # milissegundo — o que `started_at` não é.
        achados.sort(key=lambda s: s.id, reverse=True)
        return achados[:limit]
