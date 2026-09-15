"""A definição de workflow: o objeto que o motor executa E que a API serializa.

Que seja o MESMO objeto nos dois lados é o ponto. Uma definição declarativa
paralela, que descrevesse o que o motor faz, permitiria drift entre o desenho
e a execução — e um desenho que não corresponde ao motor é a decoração que o
§3.5 do spec de composição nomeia como modo de falha.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from orchestrator.matching.engine import default_resolvers
from orchestrator.workflow.resolver import Resolver

if TYPE_CHECKING:
    # Só para o type checker: um import em tempo de execução aqui não seria
    # circular hoje, mas manteria o pacote `workflow` dependendo do pacote
    # `review` só para uma anotação — o mesmo cuidado que `agent/investigator.py`
    # já toma com `Fila`. O import de verdade, usado dentro de
    # `default_definition`, é local de propósito.
    from orchestrator.review.fila import Fila


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


def default_definition(fila: "Fila | None" = None) -> WorkflowDefinition:
    """O conciliador: três regras e o revisor humano.

    Sem agente — ele é opcional, custa dinheiro, e a definição que a API serve
    precisa ser executável sem gastar um centavo.

    O revisor entra SEMPRE. Sem fila ele usa uma vazia e não emite nada, então
    a CLI e o golden ficam idênticos; com fila, ele aplica o que foi aprovado.
    Não há "definição servida" separada da "definição executada".
    """
    from orchestrator.review.fila import Fila
    from orchestrator.review.revisor import RevisorHumano

    revisor = RevisorHumano(fila=fila if fila is not None else Fila.vazia())
    return WorkflowDefinition(
        id="conciliacao",
        name="Conciliação bancária",
        stages=(
            Stage(
                name="conciliar lançamentos",
                cascade=(*default_resolvers(), revisor),
            ),
        ),
    )
