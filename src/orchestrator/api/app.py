"""O app HTTP do canvas.

Regra que governa este módulo: NENHUM endpoint daqui pode gastar dinheiro.
Não é uma flag a desligar — não existe caminho de código deste arquivo até o
modelo. Ver o §5 do spec desta fatia e o teste em `tests/api/test_execucao.py`.
"""

from fastapi import FastAPI, HTTPException

from orchestrator.api.schemas import WorkflowJSON, workflow_json
from orchestrator.workflow.definition import default_definition

app = FastAPI(title="Agent Orchestrator — canvas")

_WORKFLOWS = {"conciliacao": default_definition}


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowJSON)
def obter_workflow(workflow_id: str) -> WorkflowJSON:
    fabrica = _WORKFLOWS.get(workflow_id)
    if fabrica is None:
        raise HTTPException(status_code=404, detail=f"workflow desconhecido: {workflow_id}")
    return workflow_json(fabrica())
