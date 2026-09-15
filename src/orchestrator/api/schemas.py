"""O contrato JSON, isolado do domínio.

Os schemas são construídos A PARTIR dos objetos do domínio, nunca escritos à
mão em paralelo a eles — ver o teste anti-drift.
"""

from pydantic import BaseModel

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
