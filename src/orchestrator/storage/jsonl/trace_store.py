"""Traces em JSONL append-only, um arquivo por run.

Um arquivo por run e não um só para tudo: um trace tem dezenas a milhares de
spans, e um arquivo único faria `orchestrator-trace <id>` varrer o histórico
inteiro para achar um. `RunStore` pode ser um arquivo só porque guarda uma linha
por run; aqui a cardinalidade é outra.

Mesma disciplina de serialização de `review/serial.py`: campo a campo,
explícito, sem mágica de introspecção. Enum vira `.value`, `datetime` vira
ISO-8601, `Cost` sai com os CINCO campos — perder um faria o trace reportar
custo menor que o real, que é o defeito que P2.15 já corrigiu uma vez.
"""

import json
from datetime import datetime
from pathlib import Path

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.trace import Span, SpanKind, SpanStatus, Trace


def _para_dict(s: Span) -> dict:
    return {
        "id": s.id,
        "parent_id": s.parent_id,
        "kind": s.kind.value,
        "name": s.name,
        "status": s.status.value,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "duration_ms": s.duration_ms,
        "cost": {
            "input_tokens": s.cost.input_tokens,
            "output_tokens": s.cost.output_tokens,
            "cached_tokens": s.cost.cached_tokens,
            "cache_creation_tokens": s.cost.cache_creation_tokens,
            "calls": s.cost.calls,
        },
        "attributes": s.attributes,
        "error": s.error,
    }


def _de_dict(d: dict) -> Span:
    return Span(
        id=d["id"],
        parent_id=d["parent_id"],
        kind=SpanKind(d["kind"]),
        name=d["name"],
        status=SpanStatus(d["status"]),
        started_at=(
            datetime.fromisoformat(d["started_at"]) if d["started_at"] else None
        ),
        duration_ms=d["duration_ms"],
        cost=Cost(**d["cost"]),
        attributes=d.get("attributes") or {},
        error=d.get("error"),
    )


class JsonlTraceStore:
    def __init__(self, raiz: Path) -> None:
        self._raiz = Path(raiz)

    def _caminho(self, run_id: str) -> Path:
        return self._raiz / "traces" / f"{run_id}.jsonl"

    def save(self, trace: Trace) -> None:
        caminho = self._caminho(trace.run_id)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with caminho.open("w", encoding="utf-8") as f:
            for s in trace.spans:
                f.write(json.dumps(_para_dict(s), ensure_ascii=False, default=str) + "\n")

    def get(self, run_id: str) -> Trace | None:
        caminho = self._caminho(run_id)
        if not caminho.exists():
            return None
        spans = []
        texto = caminho.read_text(encoding="utf-8")
        for numero, linha in enumerate(texto.splitlines(), start=1):
            if not linha.strip():
                continue
            try:
                spans.append(_de_dict(json.loads(linha)))
            except Exception as erro:
                # Mesma disciplina da `Fila` e do `RunStore`: a mensagem diz
                # QUAL registro. Quem lê isso investiga um trace que não abre,
                # não um parser.
                raise ValueError(
                    f"span inválido em {caminho} na linha {numero}: {erro}"
                ) from erro
        return Trace(run_id=run_id, spans=tuple(spans))
