"""O domínio de conciliação: a implementação de referência do runtime.

Virou pacote no PR do M2, e por um motivo concreto: `agent/tools.py` guardava as
ferramentas DE CONCILIAÇÃO (buscar lançamento contábil, calcular retenção de
imposto) dentro do pacote do agente genérico — e ocupava o nome que o
`ToolRegistry` precisava. Mover o arquivo para cá resolve as duas coisas de uma
vez, e é a mesma seta que a catraca já apontava (`agent.tools -> domains`).

Os re-exports abaixo mantêm `from orchestrator.conciliacao import reconcile`
funcionando. Não são alias de compatibilidade para consumidor externo — é a
superfície pública do domínio, e ela continua sendo a mesma.
"""

from orchestrator.conciliacao.workflow import (
    ReconcileResult,
    default_definition,
    default_resolvers,
    reconcile,
)

__all__ = [
    "ReconcileResult",
    "default_definition",
    "default_resolvers",
    "reconcile",
]
