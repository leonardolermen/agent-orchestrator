"""A definição de workflow: o objeto que o motor executa E que a API serializa.

**Zero conhecimento de domínio, desde o PR #5.** Este módulo trazia
`default_definition()` — a cascata de conciliação — e por causa dela importava
o motor (para `default_resolvers`) e o pacote `review` (para o revisor). Eram
quatro das arestas ilegais da CAUSA 2, e a circularidade `engine <-> definition`
que dois imports locais escondiam. A definição PADRÃO é configuração de
produto, não parte do kernel: ela mora em `conciliacao.py`.

Que seja o MESMO objeto nos dois lados é o ponto. Uma definição declarativa
paralela, que descrevesse o que o motor faz, permitiria drift entre o desenho
e a execução — e um desenho que não corresponde ao motor é a decoração que o
§3.5 do spec de composição nomeia como modo de falha.
"""

from dataclasses import dataclass

from orchestrator.kernel.resolver import Resolver


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
