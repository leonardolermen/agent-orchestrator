"""`Tarefa`: um resolver que TRANSFORMA o item, em vez de julgá-lo.

`Agent` devolve `proposals` e nunca `resolutions` — proposta não resolve, e
isso é o tipo, não disciplina. `Tarefa` devolve `resolutions` e nunca
`proposals`, e a pergunta óbvia é por que isso é legítimo.

Não é "porque não decide". Um triador que produz `kind="urgente"` decide, e é
assim que a ramificação funciona. A distinção é outra:

    Uma `Tarefa` empurra o trabalho para frente DENTRO do run; nunca o
    encerra. O item que ela produz continua no pool e ainda passa por quem
    vier depois — inclusive um HUMANO, se a cascata tiver um. Uma `Proposal`
    que resolvesse faria o item SAIR com um julgamento que ninguém conferiu.

E isso não depende de boa vontade: `WorkflowDefinition.__post_init__` recusa
uma definição em que um kind produzido não seja consumido por ninguém nem
declarado em `entrega`. Beco sem saída é erro de construção.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from orchestrator.agent.conversa import conversar
from orchestrator.agent.llm import LLMClient
from orchestrator.agent.tools.registry import ToolRegistry
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Resolution, TraceEvent, TraceKind
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet


@dataclass(frozen=True)
class SaidaDaTarefa:
    """O que uma transformação produziu para UM item.

    `resolution=None` é abstenção: a `Tarefa` não conseguiu transformar, e o
    item não sai do pool. Não é `tuple[Resolution, tuple[WorkItem, ...]] |
    None` porque `None` já significa "formato inválido, tente de novo" no
    contrato de `conversar` — uma tupla-ou-None faria abstenção e retry de
    formato serem o mesmo valor, e o laço tentaria de novo uma tarefa que já
    desistiu. Este tipo, com `resolution=None`, diz "não resolvi" sem colidir
    com esse `None`.
    """

    cost: Cost
    trace: tuple[TraceEvent, ...]
    resolution: Resolution | None = None
    produced: tuple[WorkItem, ...] = ()


# Como o texto final do modelo vira o item transformado. Devolve `None` quando
# o texto não é utilizável — e é esse `None` que dispara o retry de formato em
# `conversar`. Devolve `SaidaDaTarefa` (com `resolution` preenchido) quando dá
# certo.
Transformador = Callable[[str, str, Cost, list[TraceEvent]], SaidaDaTarefa | None]


@dataclass(frozen=True)
class TarefaSpec:
    """A configuração de uma tarefa. DADO, não comportamento — o espelho de `AgentSpec`."""

    name: str
    system: str
    model: str
    prompt_de: Callable[[WorkItem], str]
    transformar: Transformador
    max_turns: int = 6
    max_format_retries: int = 2
    budget_microcents: int = 4_000_000


def _abster(item_id: str, motivo: str, custo: Cost, trace: list[TraceEvent]) -> SaidaDaTarefa:
    """Não transformou. Registra por quê e devolve o item ao pool.

    Não é parâmetro da spec — ao contrário de `AgentSpec.abstain`, que precisa
    do rótulo de "não sei" DO DOMÍNIO porque uma proposta de abstenção tem um
    `tipo`. Aqui não há tipo a escolher: não transformar é a ausência de
    resolução, e ausência é a mesma em todo domínio.
    """
    return SaidaDaTarefa(
        cost=custo,
        trace=(*trace, TraceEvent(kind=TraceKind.OUTCOME, detail={"motivo": motivo})),
    )


@dataclass
class Tarefa:
    """Um `Resolver` de classe AGENTE que transforma em vez de julgar.

    O laço é o mesmo de `Agent` — `conversa.conversar` — com os dois pontos de
    domínio trocados: onde `Agent` interpreta uma proposta, `Tarefa` interpreta
    uma transformação; onde `Agent` abstém com o rótulo do domínio, `Tarefa`
    abstém sem rótulo nenhum, porque não há julgamento a rotular.
    """

    spec: TarefaSpec
    client: LLMClient
    tools: ToolRegistry

    name: str = field(init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.spec.name)
        # As mesmas guardas de `Agent.__post_init__`, pelas mesmas razões: uma
        # tarefa mal configurada precisa falhar na construção, não virar uma
        # abstenção muda que parece funcionar.
        if self.spec.max_turns < 1:
            raise ValueError(f"max_turns precisa ser pelo menos 1: {self.spec.max_turns}")
        if self.spec.budget_microcents < 0:
            raise ValueError(
                f"budget_microcents não pode ser negativo: {self.spec.budget_microcents}"
            )
        # Modelo sem preço conhecido não é abstenção, é erro de configuração.
        # Abster em todo item gastaria a execução inteira sem produzir nada, e
        # o custo — métrica central do produto — ficaria incalculável. Falhar
        # aqui, uma vez, é o comportamento certo.
        Cost.zero().microcents(self.client.model)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=f"tarefa {self.spec.model}",
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        """Transforma o que recebeu. NUNCA devolve `proposals`.

        O espelho de `Agent.resolve`, e a assimetria é o contrato: lá o campo
        `resolutions` não é preenchido, aqui é `proposals`.
        """
        resolucoes, produzidos, total = [], [], Cost.zero()
        for item in work.items:
            saida = conversar(
                client=self.client,
                tools=self.tools,
                system=self.spec.system,
                item_id=item.id,
                prompt=self.spec.prompt_de(item),
                max_turns=self.spec.max_turns,
                max_format_retries=self.spec.max_format_retries,
                budget_microcents=self.spec.budget_microcents,
                interpretar=self.spec.transformar,
                desistir=_abster,
            )
            total = total + saida.cost
            # `resolution is None` é abstenção: o item NÃO sai do pool e fica
            # para o próximo degrau. Um agente que estoura não derruba o run,
            # e um item não some porque o modelo devolveu lixo.
            if saida.resolution is not None:
                resolucoes.append(saida.resolution)
                produzidos.extend(saida.produced)
        return ResolverOutput(
            resolutions=resolucoes, produced=tuple(produzidos), cost=total
        )
