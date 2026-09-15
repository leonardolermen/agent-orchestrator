"""O app HTTP do canvas.

Regra que governa este módulo: NENHUM endpoint daqui pode gastar dinheiro.
Não é uma flag a desligar — não existe caminho de código deste arquivo até o
modelo. Ver o §5 do spec desta fatia e o teste em `tests/api/test_execucao.py`.
"""

from functools import lru_cache

from fastapi import FastAPI, HTTPException

from orchestrator.api.schemas import (
    GapJSON,
    ResolverRunJSON,
    RunJSON,
    RunRequest,
    WorkflowJSON,
    workflow_json,
)
from orchestrator.cli import build_benchmark
from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate
from orchestrator.workflow.definition import default_definition

app = FastAPI(title="Agent Orchestrator — canvas")

_WORKFLOWS = {"conciliacao": default_definition}


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowJSON)
def obter_workflow(workflow_id: str) -> WorkflowJSON:
    fabrica = _WORKFLOWS.get(workflow_id)
    if fabrica is None:
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    return workflow_json(fabrica())


@app.post("/api/workflows/{workflow_id}/runs", response_model=RunJSON)
def executar(workflow_id: str, pedido: RunRequest) -> RunJSON:
    fabrica = _WORKFLOWS.get(workflow_id)
    if fabrica is None:
        # 404 antes do cache, de propósito: um id desconhecido nunca deve
        # entrar em `_executar_memoizado`, nem para ficar registrado como
        # "chave inválida" numa memoização que não sabe o que fazer com isso.
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    return _executar_memoizado(workflow_id, pedido.seed, pedido.n, pedido.taxa_divergencia)


@lru_cache(maxsize=64)
def _executar_memoizado(workflow_id: str, seed: int, n: int, taxa: float) -> RunJSON:
    """Determinístico por construção, então cacheável.

    A definição servida aqui não tem agente: a execução é pura, sem rede e sem
    custo. É isso que torna seguro um endpoint que qualquer F5 dispara. A
    chave do cache inclui `workflow_id` além dos três parâmetros do
    benchmark — dois workflows diferentes com os mesmos parâmetros não podem
    colidir na mesma entrada.
    """
    dataset = build_benchmark(seed=seed, n=n, taxa_divergencia=taxa)
    definicao = _WORKFLOWS[workflow_id]()
    resultado = reconcile(dataset.bank, dataset.ledger, definition=definicao)
    m = evaluate(dataset, resultado)

    total = m.bank_total
    por_resolver = [
        ResolverRunJSON(
            name=d.name,
            cost_class=d.cost_class.name,
            matches=m.matches_by_layer.get(d.name, 0),
            rate=m.matches_by_layer.get(d.name, 0) / total if total else 0.0,
            microcents=m.cost_by_resolver_microcents.get(d.name, 0),
        )
        for stage in definicao.stages
        for d in (r.describe() for r in stage.ordered())
    ]
    # A lacuna usa `bank_matched`, não a soma das contagens por resolver. A
    # soma assumiria que todo MatchResult carrega exatamente um id bancário —
    # verdade hoje, mas não garantida pelo tipo — e, se algum dia deixasse de
    # ser, a lacuna iria a negativo em vez de crescer. `bank_matched` já é o
    # conjunto de ids bancários casados intersectado com o dataset real (ver
    # `evaluate`), então não depende dessa suposição. Como consequência, a
    # soma `sum(rate por resolver) + gap.rate == 1.0` deixa de assumir a
    # invariante "um id bancário por match" e passa a VERIFICÁ-LA.
    total_resolvido = m.bank_matched
    return RunJSON(
        seed=seed,
        n=n,
        bank_total=total,
        deterministic_rate=m.deterministic_rate,
        by_resolver=por_resolver,
        gap=GapJSON(
            items=total - total_resolvido,
            rate=(total - total_resolvido) / total if total else 0.0,
        ),
    )
