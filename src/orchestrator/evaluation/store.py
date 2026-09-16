"""Onde os casos moram. JSONL append-only, como a fila e o run store.

**Append-only não é economia de escrita, é a garantia.** Um caso é uma
afirmação de verdade com data; reescrever o arquivo permitiria mudar o que um
caso afirmava DEPOIS de um benchmark tê-lo usado, e dois resultados da mesma
`dataset_version` passariam a discordar sem que nada denunciasse. É a mesma
razão que `Fila` documenta, com um agravante: a fila registra o que aconteceu,
e isto registra o que DEVERIA ter acontecido — se a régua muda em silêncio,
todas as medições passadas viram ficção.

**Por que `avaliacoes/casos/` vai para o git e `data/` não.** É a decisão de
ativo do projeto, e o scaffold já a implementa: `data/` é saída (runs, traces,
filas) e se regenera; o conjunto de avaliação é o que o §1.1 chama de "a coisa
que um concorrente não copia". Perder `data/` custa uma re-execução. Perder
`avaliacoes/` custa a capacidade de saber se o sistema melhorou.
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.evaluation.case import (
    EvalDataset,
    EvaluationCase,
    ExpectedOutcome,
    Provenance,
)
from orchestrator.kernel.work import WorkItem

_RAIZ_PADRAO = Path("avaliacoes") / "casos"


def caminho_do_conjunto(dataset_id: str, raiz: Path | None = None) -> Path:
    return (raiz or _RAIZ_PADRAO) / f"{dataset_id}.jsonl"


def _payload_serializavel(payload: Any) -> Any:
    """O payload de um `WorkItem` é do domínio e pode ser qualquer coisa.

    Dataclass vira dict; o resto passa como está e o `json.dumps` decide. Um
    payload que não serializa levanta AQUI, na gravação, e não meses depois na
    leitura — quando o run que o originou já não existe para regerá-lo.
    """
    if hasattr(payload, "__dataclass_fields__"):
        return asdict(payload)
    return payload


def _para_dict(caso: EvaluationCase) -> dict[str, Any]:
    return {
        "id": caso.id,
        "input_snapshot": [
            {"id": i.id, "kind": i.kind, "payload": _payload_serializavel(i.payload)}
            for i in caso.input_snapshot
        ],
        "expected": {
            "kind": caso.expected.kind,
            "should_resolve_deterministically": (
                caso.expected.should_resolve_deterministically
            ),
            "resolves_with": sorted(caso.expected.resolves_with),
            "note": caso.expected.note,
        },
        "provenance": str(caso.provenance),
        "created_at": caso.created_at.isoformat(),
        "source_run_id": caso.source_run_id,
        "tags": sorted(caso.tags),
    }


def _de_dict(d: dict[str, Any]) -> EvaluationCase:
    criado = datetime.fromisoformat(d["created_at"])
    if criado.tzinfo is None:
        # Arquivo escrito por uma versão anterior, ou à mão. Assumir UTC seria
        # silencioso; recusar é o que mantém a guarda de contaminação honesta.
        raise ValueError(
            f"caso {d['id']!r} no disco tem `created_at` sem fuso: "
            f"{d['created_at']!r}. sem instante não dá para saber se ele é "
            f"anterior a um run, e a guarda de contaminação depende disso"
        )
    e = d["expected"]
    return EvaluationCase(
        id=d["id"],
        input_snapshot=tuple(
            WorkItem(id=i["id"], kind=i["kind"], payload=i["payload"])
            for i in d["input_snapshot"]
        ),
        expected=ExpectedOutcome(
            kind=e["kind"],
            should_resolve_deterministically=e["should_resolve_deterministically"],
            resolves_with=frozenset(e.get("resolves_with", ())),
            note=e.get("note", ""),
        ),
        provenance=Provenance(d["provenance"]),
        created_at=criado,
        source_run_id=d.get("source_run_id"),
        tags=frozenset(d.get("tags", ())),
    )


class CaseStore:
    """Casos em disco. Uma linha por caso, e nenhuma linha é reescrita."""

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        self._casos: dict[str, EvaluationCase] = {}
        if caminho.exists():
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    caso = _de_dict(json.loads(linha))
                    self._casos[caso.id] = caso

    def __len__(self) -> int:
        return len(self._casos)

    def __contains__(self, case_id: str) -> bool:
        return case_id in self._casos

    def acrescentar(self, caso: EvaluationCase) -> None:
        """Grava um caso novo. Recusa sobrescrever um id existente.

        Mesma recusa de `gravar_receita` e do scaffold, e aqui pelo motivo mais
        forte dos três: substituir um caso mudaria retroativamente o
        significado de todo benchmark que já o usou.
        """
        if caso.id in self._casos:
            raise ValueError(
                f"caso {caso.id!r} já existe em {self.caminho}. substituí-lo "
                f"mudaria o significado dos benchmarks que já o mediram; se a "
                f"verdade mudou, o caso novo precisa de id novo"
            )
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.caminho.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_para_dict(caso), ensure_ascii=False) + "\n")
        self._casos[caso.id] = caso

    def dataset(self, dataset_id: str | None = None) -> EvalDataset:
        """Tudo que está no disco, como conjunto avaliável.

        Ordenado por `created_at` e depois por id: a versão já é independente
        de ordem, mas a LISTAGEM não deveria mudar entre leituras do mesmo
        arquivo — um diff de relatório que muda sozinho ensina a ignorar diffs.
        """
        return EvalDataset(
            id=dataset_id or self.caminho.stem,
            cases=tuple(
                sorted(self._casos.values(), key=lambda c: (c.created_at, c.id))
            ),
        )

    def por_procedencia(self, provenance: Provenance) -> tuple[EvaluationCase, ...]:
        return tuple(c for c in self.dataset().cases if c.provenance is provenance)

    def resumo(self) -> str:
        ds = self.dataset()
        if not ds.cases:
            return f"{self.caminho}: vazio"
        por_proc: dict[str, int] = {}
        sem_verdade = 0
        for c in ds.cases:
            por_proc[str(c.provenance)] = por_proc.get(str(c.provenance), 0) + 1
            if c.expected.kind is None:
                sem_verdade += 1
        linhas = [
            f"{self.caminho}",
            f"  casos:   {len(ds)} (versão {ds.version})",
            f"  período: {ds.cases[0].created_at.date()} → "
            f"{ds.cases[-1].created_at.date()}",
        ]
        for proc, n in sorted(por_proc.items()):
            linhas.append(f"  {proc:<14} {n}")
        if sem_verdade:
            # Não é defeito: é o que um `rejeitar` produz. Aparece no resumo
            # porque estes casos não entram no denominador da precisão, e quem
            # lê "200 casos" precisa saber que 40 deles não pontuam tipo.
            linhas.append(
                f"  sem tipo esperado: {sem_verdade} "
                f"(ensinam a abster; não entram na precisão)"
            )
        return "\n".join(linhas)


def agora() -> datetime:
    return datetime.now(UTC)
