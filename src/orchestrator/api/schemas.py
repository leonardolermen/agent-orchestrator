"""O contrato JSON, isolado do domínio.

Os schemas são construídos A PARTIR dos objetos do domínio, nunca escritos à
mão em paralelo a eles — ver o teste anti-drift.
"""

from pydantic import BaseModel, Field

from orchestrator.workflow.definition import Stage, WorkflowDefinition


class ResolverJSON(BaseModel):
    name: str
    cost_class: str
    summary: str


class StageJSON(BaseModel):
    name: str
    cascade: list[ResolverJSON]


class WorkflowJSON(BaseModel):
    id: str
    name: str
    stages: list[StageJSON]


class RunRequest(BaseModel):
    """O pedido de execução do benchmark sintético.

    Os limites de `Field` são o que faz o FastAPI devolver 422 sozinho para
    uma `taxa_divergencia` fora de [0, 1] — em vez de deixar `build_benchmark`
    levantar `ValueError` e a rota devolver 500.
    """

    seed: int = Field(default=1, ge=0)
    n: int = Field(default=300, ge=1, le=5000)
    taxa_divergencia: float = Field(default=0.15, ge=0.0, le=1.0)


class ResolverRunJSON(BaseModel):
    name: str
    cost_class: str
    matches: int
    rate: float
    microcents: int


class GapJSON(BaseModel):
    items: int
    rate: float


class RunJSON(BaseModel):
    seed: int
    n: int
    bank_total: int
    deterministic_rate: float
    by_resolver: list[ResolverRunJSON]
    gap: GapJSON


def stage_json(stage: Stage) -> StageJSON:
    return StageJSON(
        name=stage.name,
        cascade=[
            ResolverJSON(name=d.name, cost_class=d.cost_class.name, summary=d.summary)
            for d in (r.describe() for r in stage.ordered())
        ],
    )


def workflow_json(definicao: WorkflowDefinition) -> WorkflowJSON:
    return WorkflowJSON(
        id=definicao.id,
        name=definicao.name,
        stages=[stage_json(s) for s in definicao.stages],
    )
