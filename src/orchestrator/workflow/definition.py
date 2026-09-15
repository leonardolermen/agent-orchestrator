"""A definição de workflow: o objeto que o motor executa E que a API serializa.

Que seja o MESMO objeto nos dois lados é o ponto. Uma definição declarativa
paralela, que descrevesse o que o motor faz, permitiria drift entre o desenho
e a execução — e um desenho que não corresponde ao motor é a decoração que o
§3.5 do spec de composição nomeia como modo de falha.
"""

from dataclasses import dataclass

from orchestrator.matching.engine import default_resolvers
from orchestrator.workflow.resolver import Resolver


@dataclass(frozen=True)
class Stage:
    name: str
    cascade: tuple[Resolver, ...]

    def ordered(self) -> list[Resolver]:
        """A cascata na ordem em que roda.

        `sorted` é estável: a ordem entre classes de custo é derivada, a ordem
        dentro de uma classe é a que o autor da definição escreveu.
        """
        return sorted(self.cascade, key=lambda r: r.cost_class)


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    stages: tuple[Stage, ...]


def default_definition() -> WorkflowDefinition:
    """O conciliador determinístico.

    Sem agente: o agente é opcional, custa dinheiro, e a definição que a API
    serve precisa ser executável sem gastar um centavo. O que as regras não
    resolvem aparece como LACUNA na tela — que é informação, não omissão.
    """
    return WorkflowDefinition(
        id="conciliacao",
        name="Conciliação bancária",
        stages=(
            Stage(name="conciliar lançamentos", cascade=tuple(default_resolvers())),
        ),
    )
