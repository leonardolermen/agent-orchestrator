"""`Run`: a execução como entidade.

Até o PR #7, execução não existia como coisa. O que havia era
`_executar_memoizado(workflow_id, seed, n, taxa)` com `@lru_cache(maxsize=64)`
em `api/app.py` — um run store disfarçado de memoização, cujo próprio docstring
admitia que a função tinha deixado de ser pura e que por isso o POST de decisão
precisava chamar `cache_clear()`.

Sem `Run` não há o que observar, pausar, retomar, comparar ou avaliar:
observabilidade, human-in-the-loop formal e evaluation param todos aqui. É por
isso que ele é M1 e não M6.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.policy import PolicyDecision
from orchestrator.kernel.resolution import Proposal, Resolution
from orchestrator.kernel.work import WorkSet


class RunState(StrEnum):
    """Os estados de uma execução.

    `AGUARDANDO_HUMANO` é o que hoje existe DE FATO mas não de nome: "sobraram
    itens e a cascata tem um resolver de classe HUMANO". Nomeá-lo é o que
    permite a API responder "este run está esperando você" em vez de devolver
    uma lacuna sem explicação — e é o pré-requisito de `resume()` (M7).
    """

    PENDENTE = "pendente"
    EXECUTANDO = "executando"
    AGUARDANDO_HUMANO = "aguardando_humano"
    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    CANCELADO = "cancelado"


def new_run_id(agora: datetime | None = None) -> str:
    """Id ordenável por tempo, sem dependência nova.

    ULID seria o certo e custaria uma dependência de runtime num pacote que tem
    uma. Milissegundos em base 10 com sufixo aleatório ordena
    lexicograficamente pelo mesmo motivo que um ULID, e `sorted(ids)` é a
    listagem "mais recentes primeiro" que o dashboard (M11) precisa sem índice.
    """
    ms = int((agora or datetime.now(UTC)).timestamp() * 1000)
    return f"{ms:013d}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class Run:
    """Uma execução: o que rodou, sobre o quê, com que resultado e a que custo.

    `unresolved` é o `WorkSet` que sobrou, não uma lista de pendências já
    traduzida: quem sabe o que "pendência" significa é o domínio. É a mesma
    razão de `ExecutionResult.unresolved` existir assim desde o PR #5.
    """

    id: str
    workflow_id: str
    workflow_version: str
    state: RunState
    started_at: datetime
    input_ref: str
    resolutions: tuple[Resolution, ...] = ()
    proposals: tuple[Proposal, ...] = ()
    unresolved: WorkSet = field(default_factory=WorkSet)
    cost_by_resolver: dict[str, Cost] = field(default_factory=dict)
    resolved_by_resolver: dict[str, int] = field(default_factory=dict)
    resolutions_by_class: dict[CostClass, list[Resolution]] = field(default_factory=dict)
    # POR QUE o runtime fez o que fez. Sem isto, uma execução em que a
    # política pulou o agente é indistinguível de uma em que o agente não achou
    # nada — a mesma ambiguidade que `proposals_api_failed` elimina em
    # `agent_eval.py`.
    policy_decisions: tuple[PolicyDecision, ...] = ()
    finished_at: datetime | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        # Mesma exigência de `Decision.quando`, e pelo mesmo motivo: horário
        # ingênuo não é um instante, e a listagem de runs depende de ordem.
        if self.started_at.tzinfo is None:
            raise ValueError("`started_at` precisa de fuso (use UTC)")
        if self.finished_at is not None and self.finished_at.tzinfo is None:
            raise ValueError("`finished_at` precisa de fuso (use UTC)")

    @property
    def duration_ms(self) -> int | None:
        if self.finished_at is None:
            return None
        return int((self.finished_at - self.started_at).total_seconds() * 1000)

    def cost_total(self) -> Cost:
        total = Cost.zero()
        for c in self.cost_by_resolver.values():
            total = total + c
        return total

    def custo_total_microcents(self, model: str) -> int:
        """Soma em micro-centavos. Um resolver que não gastou token nenhum
        converte para zero em qualquer modelo — a mesma guarda que
        `metrics.evaluate` já aplica, para que uma cascata só de regras não
        exija um `model` válido para ler zero."""
        return sum(
            c.microcents(model) if c != Cost.zero() else 0
            for c in self.cost_by_resolver.values()
        )
