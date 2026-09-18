"""Conciliação bancária: UM domínio, do lado de `procurement` e `swe`.

Morou na raiz do pacote por muito tempo — `models.py`, `taxonomy.py`, `money.py`,
`dates.py`, `tax.py`, `matching/`, `synth/` e `conciliacao/` espalhados entre os
módulos do framework —, e enquanto morou, o repositório inteiro parecia um
produto de conciliação em vez de um runtime capaz de expressar qualquer domínio.
Eram 22 entradas na tabela `DESTINO` dizendo, uma a uma, que aquele não era o
lugar.

A §19.5 do spec já tinha decidido o desfecho: a conciliação é "rebaixada a
implementação de referência" e "migrada como qualquer outro domínio". A regra
nº 2 da §4.2 é a razão: **nenhuma camada importa `domains/` — se precisar, o
conceito está na camada errada.**

Ela continua sendo a implementação de referência, e continua sendo onde se olha
para ver o runtime inteiro funcionando de ponta a ponta. O que ela não é mais é
privilegiada. O vocabulário segue em português porque o termo é do domínio
(ADR-10): o que mudou foi o diretório, não a língua.

Os re-exports abaixo são a superfície pública do domínio — o que a CLI, a API e
o grill consomem.
"""

from orchestrator.domains.reconciliation.workflow import (
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
