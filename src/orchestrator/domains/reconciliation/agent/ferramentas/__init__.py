"""As ferramentas do agente investigador: uma por arquivo.

Era um módulo só, e nele a ferramenta vivia partida em dois: a lógica como
método de `ToolContext`, a forma numa lista `_FERRAMENTAS` cem linhas abaixo, e
um `getattr(contexto, nome)` costurando os dois na hora de despachar. Acrescentar
uma ferramenta era tocar três lugares, e ler uma era pular entre eles.

Agora cada arquivo é UMA ferramenta: a função e o `ToolSpec` que o modelo vê,
lado a lado, com o comentário que explica a decisão de cada campo junto do campo.
Este `__init__` só as enfileira.

**O que sobrou de join, e por que é seguro.** `SPEC.name` é uma string e
`SPEC.fn` é uma função; em tese podem divergir. Na prática estão a dez linhas de
distância um do outro, e `test_nome_da_ferramenta_e_o_nome_da_funcao` recusa a
divergência — a mesma disciplina de antes, com a verificação no lugar onde ela
se lê.

A ORDEM desta lista é a ordem em que os schemas chegam ao modelo, e ela é
estável de propósito: o system prompt e os schemas são marcados para cache
(`anthropic_client`), e cache com ordem instável é cache que nunca acerta.
"""

from typing import Any

from orchestrator.agent.tools.registry import ToolRegistry, ToolSpec
from orchestrator.domains.reconciliation.agent.ferramentas.buscar_documento_fiscal import (
    SPEC as BUSCAR_DOCUMENTO_FISCAL,
)
from orchestrator.domains.reconciliation.agent.ferramentas.buscar_lancamentos import (
    SPEC as BUSCAR_LANCAMENTOS,
)
from orchestrator.domains.reconciliation.agent.ferramentas.calcular_retencao import (
    SPEC as CALCULAR_RETENCAO,
)
from orchestrator.domains.reconciliation.agent.ferramentas.calendario_bancario import (
    SPEC as CALENDARIO_BANCARIO,
)
from orchestrator.domains.reconciliation.agent.ferramentas.contexto import ToolContext, ledger_dict
from orchestrator.domains.reconciliation.agent.ferramentas.historico_fornecedor import (
    SPEC as HISTORICO_FORNECEDOR,
)

# TODAS são somente-leitura. O agente não escreve em lugar nenhum — ele produz
# uma proposta, e quem escreve é o humano ao aprovar. É isso que elimina deste
# plano compensação, idempotência e rollback (§6.5), e o `ToolRegistry` recusa
# registrar uma WRITE que não declare a compensadora.
FERRAMENTAS: tuple[ToolSpec, ...] = (
    BUSCAR_LANCAMENTOS,
    BUSCAR_DOCUMENTO_FISCAL,
    HISTORICO_FORNECEDOR,
    CALCULAR_RETENCAO,
    CALENDARIO_BANCARIO,
)


def catalogo_de_ferramentas() -> ToolRegistry:
    """As cinco ferramentas, SEM dados. Para listar, validar e montar schema."""
    return ToolRegistry(list(FERRAMENTAS))


def registry_de(contexto: ToolContext) -> ToolRegistry:
    """As cinco ferramentas do investigador, ligadas a dados e executáveis."""
    return catalogo_de_ferramentas().com_contexto(contexto)


# Os schemas que o modelo vê, DERIVADOS do registro em vez de escritos ao lado
# dele. É a metade do join frágil que sobrevive por ser consumida por quem não
# tem um `ToolContext` na mão: o servidor MCP de `eval/assinatura.py` monta as
# ferramentas a partir da forma, e liga a função por conta própria.
TOOL_SCHEMAS: list[dict[str, Any]] = catalogo_de_ferramentas().schemas()

__all__ = [
    "FERRAMENTAS",
    "TOOL_SCHEMAS",
    "ToolContext",
    "catalogo_de_ferramentas",
    "ledger_dict",
    "registry_de",
]
