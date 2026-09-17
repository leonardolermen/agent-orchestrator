"""`Tarefa`: um resolver que TRANSFORMA o item, em vez de julgá-lo.

`Agent` devolve `proposals` e nunca `resolutions` — proposta não resolve, e
isso é o tipo, não disciplina. `Tarefa` devolve `resolutions` e nunca
`proposals`, e a pergunta óbvia é por que isso é legítimo.

Não é "porque não decide". Um triador que produz `kind="urgente"` decide, e é
assim que a ramificação funciona.

**A resposta que este módulo dava antes era maior do que os fatos.** Ela dizia
que o item produzido "ainda passa por quem vier depois — inclusive um HUMANO,
se a cascata tiver um", e tratava `WorkflowDefinition.__post_init__` como se
fechasse a questão. Todo o peso estava no *se*, e a guarda não tem opinião
nenhuma sobre ele. A restatement honesta:

**O que a guarda de beco sem saída PROVA.** Nenhum kind produzido sai do grafo
sem nome: ou algum stage o consome, ou o autor o declarou em `entrega`. Ela
pega o kind digitado errado e o kind esquecido, que de outro modo acumulariam
no pool para sempre, e obriga o autor a ESCREVER que um kind é terminal em vez
de descobri-lo por acidente.

**O que ela NÃO prova, e é a parte que estava sendo vendida.** Ela não exige
humano em lugar nenhum. Não exige que o consumidor de um kind seja outra coisa
além de mais um modelo. Não exige que uma transformação produza coisa alguma —
isso quem passou a exigir é `_conferir`, aqui embaixo, em runtime e por item.
Um run pode terminar na saída de um modelo, com `RunState.CONCLUIDO`, sem que
ninguém confira nada: `domains/redacao` é exatamente essa forma, e
`test_a_guarda_nao_exige_humano` fixa isso como limitação documentada.

**A invariante que sobrevive é a literal, e só ela:** uma `Proposal` continua
sem conseguir chegar a `WorkSet.without()` ou a `WorkSet.com()` — não existe
assinatura por onde ela passe. A propriedade mais larga — *"o julgamento de um
modelo nunca remove um item sem um humano confirmar"* — **não** é preservada
pela forma do grafo. Quem a quiser tem de pôr um resolver de classe `HUMANO`
consumindo o kind terminal; nada neste arquivo, nem no kernel, faz isso por
ele.
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
#
# O quarto argumento — `trace` — é o rastro da conversa inteira até aqui:
# turnos, chamadas de ferramenta, custo por turno. `Tarefa.resolve` NÃO o
# anexa a lugar nenhum por conta própria; quem decide se ele sobrevive é o
# próprio `Transformador`, colocando-o em `Resolution.evidence` ao construir
# a resolução — o campo já existe para isso (`kernel/resolution.py`). Um
# `transformar` que descarta este argumento produz uma `Resolution` sem
# rastro, e "uma proposta sem rastro é uma afirmação sem fonte"
# (`kernel/resolution.py`) vale igual para uma resolução.
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

    # I1 — teto por EXECUÇÃO, além do teto por item. Sem ele, um pool de N
    # itens pode gastar até N × `budget_microcents` sem nenhum disjuntor — e
    # `Tarefa` é MAIS exposta a isso que `Agent`: ela existe para mastigar
    # pools inteiros de itens transformáveis, e uma execução descontrolada aí
    # é conta real. Mesmo default e mesmo padrão de `AgentSpec`: cobre um lote
    # de ~100 itens no pior caso, o que já é caro demais para um operador não
    # perceber antes de acontecer de novo.
    budget_total_microcents: int = 400_000_000


def _abster(item_id: str, motivo: str, custo: Cost, trace: list[TraceEvent]) -> SaidaDaTarefa:
    """Não transformou: devolve o item ao pool com o motivo anexado ao rastro.

    "Anexado ao rastro" é o alcance real, e é menos do que parece: quem chama
    — `Tarefa.resolve` — descarta `saida.trace` de uma abstenção, porque
    `ResolverOutput` não tem onde pô-lo. Ver a lacuna declarada no teto de
    orçamento, em `Tarefa.resolve`.

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
        if self.spec.budget_total_microcents < 0:
            raise ValueError(
                f"budget_total_microcents não pode ser negativo: "
                f"{self.spec.budget_total_microcents}"
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
            if total.microcents(self.client.model) > self.spec.budget_total_microcents:
                # I1: estourar o teto da EXECUÇÃO pula o restante do lote sem
                # sequer chamar o modelo. Diferente de `Agent`, não há
                # proposta a emitir aqui: o item pulado simplesmente não
                # resolve e fica no pool, do mesmo jeito que qualquer
                # abstenção já fica.
                #
                # **LACUNA CONHECIDA, e o comentário anterior a negava.** Ele
                # dizia que o teto é "evento observável, não exceção". Não é:
                # é SILENCIOSO. O `TraceEvent(OUTCOME)` que `_abster` monta
                # morre aqui — `saida.trace` é descartado, `saida.cost` é
                # `Cost.zero()`, e nenhum artefato do run registra que esta
                # `Tarefa` desistiu nem por quê. Vale para as DUAS
                # desistências: esta, e a que volta de `conversar`. Onde a
                # abstenção de um `Agent` vira `Proposal` em `Run.proposals` e
                # daí um span `ABSTENCAO`, a de uma `Tarefa` não vira nada.
                #
                # `ResolverOutput` não tem canal para isso hoje, e inventar um
                # é desenho, não correção. O canal certo é o mesmo que
                # `observability/collector.py` já declara como bloqueador do
                # rastro por item: `Resolver.resolve(work, ctx)` com um
                # contexto de execução, agendado para o M6. Até lá a lacuna
                # fica DECLARADA aqui em vez de maquiada.
                saida = _abster(
                    item.id, "orçamento total da execução esgotado", Cost.zero(), []
                )
                total = total + saida.cost
                continue
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
                self._conferir(item, saida)
                resolucoes.append(saida.resolution)
                produzidos.extend(saida.produced)
        return ResolverOutput(
            resolutions=resolucoes, produced=tuple(produzidos), cost=total
        )

    def _conferir(self, item: WorkItem, saida: SaidaDaTarefa) -> None:
        """As duas metades de "transformar é resolver", impostas.

        A §3.1 do spec afirma a conjunção — uma `Resolution` consumindo A **e**
        um `produced` com B. Nada no TIPO a impunha: `SaidaDaTarefa` permite
        `resolution` sem `produced`, e `Resolution.item_ids` é um conjunto
        livre. As duas brechas têm o mesmo efeito, que é o pior possível aqui:
        um item sai do pool sem que nada o substitua, por julgamento de modelo.

        Falha ALTO, e não por abstenção, porque isto é erro de CONFIGURAÇÃO —
        um `transformar` mal escrito, não um modelo que devolveu lixo. Abster
        aqui esconderia um bug de domínio atrás de uma suíte verde, que é a
        falha oposta e pior da que a abstenção previne.
        """
        if not saida.produced:
            # Transformação que não produz nada NÃO é abstenção: abstenção é
            # `resolution=None`, e confundir as duas faria o item desaparecer
            # do run em silêncio.
            raise ValueError(
                f"{self.name!r} resolveu {item.id!r} sem produzir nada: "
                f"transformar é resolver E produzir, nunca só resolver "
                f"(abstenção é `resolution=None`)"
            )
        esperado = frozenset({item.id})
        if saida.resolution is not None and saida.resolution.item_ids != esperado:
            # `Tarefa` recebe UM item e resolve ESSE item. Consumir outros é um
            # `transformar` alcançando fora do seu mandato — e `WorkSet.
            # without()` honraria o pedido sem reclamar, porque ela descarta
            # id que não foi perguntado sem dizer nada.
            raise ValueError(
                f"{self.name!r} resolveu ids fora do item que recebeu: "
                f"esperado {sorted(esperado)}, veio "
                f"{sorted(saida.resolution.item_ids)}"
            )
