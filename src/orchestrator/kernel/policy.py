"""A política de execução: como o runtime decide o que roda, e registra por quê.

**Esta é a tese do projeto.** Até aqui a cascata era ordenada por custo
(`Stage.ordered()`) e o motor rodava TODOS os resolvers, sempre. A ordenação é
uma heurística global excelente — é ela que entrega os 85,3% por centavos — mas
é cega ao item: uma divergência de R$ 3,00 e uma de R$ 300.000,00 recebem o
mesmo tratamento e o mesmo orçamento.

O motor de política é a diferença entre "cascata barata→cara" e "runtime que
decide". É também o item da comparação com CrewAI onde não há equivalente do
outro lado: lá, todo passo é um agente.

**O que ele NÃO faz:** inverter a ordem de custo. `Stage.ordered()` continua
sendo a ordem; a política decide se cada resolver DA ORDEM roda. As duas coisas
são ortogonais, e mantê-las ortogonais é o que impede a política de poder chamar
inteligência antes da regra de graça — a invariante nº 2 do §1.5.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.work import WorkItem


class Autonomy(IntEnum):
    """Quanto o sistema pode fazer sozinho. A ordem é o significado."""

    OBSERVAR = 0
    PROPOR = 1
    AGIR_SE_SEGURO = 2
    AGIR = 3


class Route(StrEnum):
    EXECUTAR = "executar"
    PULAR = "pular"
    PARAR = "parar"


@dataclass(frozen=True)
class Budget:
    """Tetos de gasto. `None` significa sem teto, explicitamente.

    Entra agora, e não no PR #2 junto com `CostClass.CREW`, porque só agora tem
    chamador. Tipo sem chamador é capacidade especulativa — ver P6.10.
    """

    per_item_microcents: int | None = None
    per_run_microcents: int | None = None
    per_run_ms: int | None = None

    def __post_init__(self) -> None:
        for nome in ("per_item_microcents", "per_run_microcents", "per_run_ms"):
            valor = getattr(self, nome)
            if valor is not None and valor < 0:
                # Teto negativo faria a primeira comparação já nascer estourada:
                # tudo pularia sem nunca rodar, e pareceria uma política
                # funcionando com orçamento zerado em vez de configuração
                # inválida. Mesma guarda do `Investigator.__post_init__`.
                raise ValueError(f"{nome} não pode ser negativo: {valor}")

    def exceeded_by(self, spent: Cost, model: str, elapsed_ms: int = 0) -> str | None:
        """O nome do teto estourado, ou `None`. NUNCA levanta.

        Estourar orçamento é evento observável, não exceção — é a política que
        `Investigator.investigate` já aplicava, elevada ao kernel.
        """
        if self.per_run_microcents is not None:
            gasto = spent.microcents(model) if spent != Cost.zero() else 0
            if gasto > self.per_run_microcents:
                return "per_run_microcents"
        if self.per_run_ms is not None and elapsed_ms > self.per_run_ms:
            return "per_run_ms"
        return None


@dataclass(frozen=True)
class ExecutionPolicy:
    """Como decidir o que roda. Dado congelado e comparável.

    Ser um dataclass serializável é o que permite ao benchmark de M6 tratar a
    política como VARIÁVEL DE EXPERIMENTO — rodar o mesmo dataset com duas e
    comparar precisão contra custo, do mesmo jeito que `agent_eval` já compara
    modelos. Política que não é dado não é comparável, e política incomparável
    é opinião.
    """

    budget: Budget = field(default_factory=Budget)
    autonomy: Autonomy = Autonomy.PROPOR
    max_cost_class: CostClass = CostClass.HUMANO
    # Fração do valor em risco que se admite gastar para resolver um item.
    # `None` desliga a regra 7.
    max_cost_ratio: float | None = None
    # Predicados do DOMÍNIO, injetados. O kernel não sabe o que é "valor em
    # risco" — ele só sabe chamar um `Callable` e registrar o resultado.
    skip_when: Callable[[WorkItem, "PolicyContext"], bool] | None = None
    escalate_when: Callable[[WorkItem, "PolicyContext"], bool] | None = None


@dataclass(frozen=True)
class PolicyDecision:
    """POR QUE o runtime fez o que fez. Vai no `Run` e no trace.

    Sem este registro, uma execução em que a política pulou o agente é
    indistinguível de uma em que o agente não achou nada — a mesma classe de
    ambiguidade que `proposals_api_failed` existe para eliminar em
    `agent_eval.py`.

    É a informação que diferencia "o agente não achou nada" de "a política não
    deixou o agente rodar", e é a decisão mais valiosa do sistema: a única que
    economiza dinheiro.
    """

    resolver_name: str
    route: Route
    reason: str
    item_id: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class PolicyContext:
    """O que a política sabe do ambiente no momento de decidir.

    `value_at_risk` e `estimated_cost` são fornecidos pelo DOMÍNIO. O kernel não
    sabe o que vale um item nem quanto custa investigá-lo; ele sabe chamar e
    registrar. Devolver `None` em `value_at_risk` significa "esta regra não se
    aplica aqui" — e não se aplicar é diferente de aplicar e passar, o que o
    `reason` da decisão registra.
    """

    model: str
    spent: Cost = field(default_factory=Cost.zero)
    elapsed_ms: int = 0
    cancelled: bool = False
    value_at_risk: Callable[[WorkItem], int | None] | None = None
    estimated_cost: Callable[[str], int] | None = None
    unavailable: Callable[[str], str | None] | None = None
