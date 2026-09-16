"""Tripulações: vários agentes num item de trabalho.

`PERMITIDO["crew"]` é `{kernel, agent}`. Um Crew é um `Resolver` de classe
`CostClass.CREW` e nada mais — ele não conhece o motor, não conhece a política e
não conhece o humano, porque herda tudo isso por ser um resolver na cascata.
"""

from orchestrator.crew.context import ContextEntry, SharedContext
from orchestrator.crew.crew import Conflito, Crew, Process

__all__ = ["ContextEntry", "SharedContext", "Conflito", "Crew", "Process"]
