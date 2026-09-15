"""A forma serializável de um workflow, e a construção que a valida.

A receita é ENTRADA, não descrição servida: o loader constrói o objeto de
verdade e é esse objeto que a API serializa. O invariante do `definition.py` —
nunca uma descrição paralela ao motor — fica intacto.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tools import ToolContext
from orchestrator.grill.catalogo import CATALOGO, ClienteAusente
from orchestrator.review.fila import Fila
from orchestrator.workflow.definition import Stage, WorkflowDefinition

PADRAO_ID = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
ID_RESERVADOS = frozenset({"conciliacao"})


def validar_id(workflow_id: str) -> None:
    """Único lugar onde a forma de um id é decidida.

    Chamado pelo entrevistador (antes do primeiro turno, para não desperdiçar
    a conversa do parceiro) e pelo registro (antes de montar caminho, porque um
    id com `../` escreveria fora de `data/`). Dois pontos de chamada, uma
    lógica.
    """
    if not PADRAO_ID.match(workflow_id):
        raise ValueError(
            f"id inválido: {workflow_id!r}. use minúsculas, dígitos e hífen, "
            f"começando por letra, de 3 a 40 caracteres"
        )
    if workflow_id in ID_RESERVADOS:
        raise ValueError(f"id reservado: {workflow_id!r}")


@dataclass(frozen=True)
class ResolverReceita:
    nome: str
    parametros: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Receita:
    id: str
    nome: str
    justificativa: str
    gerado_em: datetime
    resolvers: tuple[ResolverReceita, ...]


def para_json(r: Receita) -> dict[str, Any]:
    return {
        "id": r.id,
        "nome": r.nome,
        "justificativa": r.justificativa,
        "gerado_em": r.gerado_em.isoformat(),
        # Ordem verbatim: é o que o modelo propôs. `Stage.ordered()` impõe a
        # ordem entre classes na EXECUÇÃO; reordenar aqui apagaria a intenção.
        "resolvers": [{"nome": x.nome, "parametros": dict(x.parametros)} for x in r.resolvers],
    }


def de_json(d: dict[str, Any]) -> Receita:
    return Receita(
        id=d["id"],
        nome=d["nome"],
        justificativa=d["justificativa"],
        gerado_em=datetime.fromisoformat(d["gerado_em"]),
        resolvers=tuple(
            ResolverReceita(nome=x["nome"], parametros=dict(x.get("parametros", {})))
            for x in d["resolvers"]
        ),
    )


def construir(
    receita: Receita,
    *,
    fila: Fila | None = None,
    cliente: LLMClient | None = None,
    context: ToolContext | None = None,
) -> WorkflowDefinition:
    """Valida construindo. Se retorna, a receita roda.

    Levantar `ValueError` aqui é o canal pelo qual o entrevistador devolve o
    erro ao modelo para ele corrigir — por isso as mensagens são escritas para
    serem lidas por um modelo, não só por uma pessoa.

    `is None` e não `or`: defensivo, não corretivo. Hoje `Fila`, `ToolContext`
    e `ClienteAusente` não definem `__bool__` nem `__len__`, então nenhum dos
    três é falsy e `or` se comportaria hoje identicamente a `is None`. A
    disciplina existe para o dia em que alguém acrescentar um `__len__` a
    `Fila` (por exemplo, `len(fila) == 0`) — nesse dia, um `or` trocaria
    silenciosamente uma fila vazia explícita pelo default, e um `is None`
    continuaria correto sem precisar mudar.
    """
    if fila is None:
        fila = Fila.vazia()
    if cliente is None:
        cliente = ClienteAusente()
    if context is None:
        context = ToolContext([], [])

    if not receita.resolvers:
        raise ValueError("a cascata precisa de pelo menos um resolver")

    vistos: set[str] = set()
    resolvers = []
    for item in receita.resolvers:
        entrada = CATALOGO.get(item.nome)
        if entrada is None:
            raise ValueError(
                f"resolver desconhecido: {item.nome!r}. disponíveis: {sorted(CATALOGO)}"
            )
        if item.nome in vistos:
            raise ValueError(
                f"resolver repetido na cascata: {item.nome!r}. o segundo rodaria "
                f"sobre o pool que o primeiro já esvaziou e casaria zero"
            )
        vistos.add(item.nome)

        conhecidos = {p.nome for p in entrada.parametros}
        desconhecidos = sorted(set(item.parametros) - conhecidos)
        if desconhecidos:
            raise ValueError(
                f"parâmetro desconhecido para {item.nome!r}: {desconhecidos}. "
                f"aceitos: {sorted(conhecidos)}"
            )

        resolvers.append(
            entrada.construir(dict(item.parametros), fila=fila, cliente=cliente, context=context)
        )

    return WorkflowDefinition(
        id=receita.id,
        name=receita.nome,
        stages=(Stage(name="conciliar lançamentos", cascade=tuple(resolvers)),),
    )
