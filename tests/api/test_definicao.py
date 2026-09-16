import pytest

pytest.importorskip("fastapi")

from dataclasses import dataclass

from fastapi.testclient import TestClient

from orchestrator.api.app import app
from orchestrator.api.schemas import stage_json
from orchestrator.kernel.cost import CostClass
from orchestrator.workflow.definition import Stage, default_definition
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet

cliente = TestClient(app)


@dataclass(frozen=True)
class ResolverFalso:
    """Stub mínimo de Resolver.

    Só o suficiente para montar uma cascata com uma classe de custo escolhida
    a dedo, sem depender de nenhum resolver de verdade — e, em especial, sem
    colocar um agente em `default_definition`, que continua sem agente por
    design.
    """

    name: str
    cost_class: CostClass

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput()

    def describe(self) -> ResolverDescription:
        return ResolverDescription(name=self.name, cost_class=self.cost_class, summary="stub")


def test_json_da_definicao_bate_com_a_definicao_real():
    # ANTI-DRIFT. Se alguém hardcodar a cascata no schema, a tela passa a
    # desenhar uma coisa e o motor a executar outra — que é exatamente a
    # decoração do §3.5 do spec de composição. Este teste existe para tornar
    # isso impossível de passar despercebido.
    esperado = default_definition()

    corpo = cliente.get("/api/workflows/conciliacao").json()

    assert corpo["id"] == esperado.id
    assert [s["name"] for s in corpo["stages"]] == [s.name for s in esperado.stages]
    for stage_body, stage in zip(corpo["stages"], esperado.stages, strict=True):
        # Comparação por registro completo, não só por nome: `name` sozinho
        # não pegaria um `cost_class` (ou `summary`) hardcodado no schema, e
        # `cost_class` é justamente o campo do qual a ordenação da cascata
        # depende para ser confiável na tela.
        descricoes = [r.describe() for r in stage.ordered()]
        assert [(r["name"], r["cost_class"], r["summary"]) for r in stage_body["cascade"]] == [
            (d.name, d.cost_class.name, d.summary) for d in descricoes
        ]


def test_stage_json_ordena_pela_ordem_de_execucao_nao_pela_de_declaracao():
    # `default_definition()` só tem resolvers REGRA, então
    # `[r["cost_class"] for r in cascade]` já sai ordenado mesmo que
    # `stage_json` não ordene nada — um teste contra o endpoint não pinaria
    # ordenação nenhuma. Aqui construímos o Stage direto, com um AGENTE
    # declarado ANTES de um REGRA, e chamamos `stage_json` — se a função
    # devolvesse `stage.cascade` em vez de `stage.ordered()`, este teste
    # falharia.
    stage = Stage(
        name="stage de teste",
        cascade=(
            ResolverFalso(name="agente-declarado-primeiro", cost_class=CostClass.AGENTE),
            ResolverFalso(name="regra-declarada-depois", cost_class=CostClass.REGRA),
        ),
    )

    corpo = stage_json(stage)

    assert [r.name for r in corpo.cascade] == [
        "regra-declarada-depois",
        "agente-declarado-primeiro",
    ]
    # A ordenação só é digna de confiança na tela se o `cost_class` de cada
    # posição também vier correto — do contrário a sequência de nomes acima
    # poderia estar certa por acaso enquanto o campo que a cascata inteira
    # existe para ordenar estivesse hardcodado ou trocado.
    assert [r.cost_class for r in corpo.cascade] == ["REGRA", "AGENTE"]


def test_workflow_inexistente_da_404():
    assert cliente.get("/api/workflows/nao-existe").status_code == 404
