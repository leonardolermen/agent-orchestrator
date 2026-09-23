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
    # Bateu `WorkflowDefinition.max_rondas` sem convergir. NÃO é `CONCLUIDO`:
    # o trabalho não acabou, o teto é que chegou. Mesmo espírito de
    # `AGUARDANDO_HUMANO` — a lacuna é declarada, nunca escondida.
    LIMITE_DE_RONDAS = "limite_de_rondas"
    # Bateu o teto de GASTO da execução, e itens ficaram sem sequer ser
    # tentados. Irmão do de cima, e separado dele de propósito: os dois são
    # "parou por um teto", mas dizer `LIMITE_DE_RONDAS` sobre um teto de
    # dinheiro mandaria quem opera mexer em `max_rondas` para resolver um
    # problema de orçamento.
    #
    # E é a distinção com `CONCLUIDO` que importa mais. Um run que o pedido
    # PROIBIU de trabalhar não terminou: ele parou antes. `CONCLUIDO` com
    # lacuna cheia e custo zero é a mesma mentira tranquila que
    # `LIMITE_DE_RONDAS` existe para não contar — só que sobre dinheiro, onde
    # ela é mais cara.
    #
    # Quem o atribui NÃO é o motor: o teto por requisição vive no cliente
    # (`agent/teto.py`), que `execute()` por desenho não inspeciona. Quem sabe
    # é a borda que o construiu — ver `api/app.py::_executar`.
    LIMITE_DE_CUSTO = "limite_de_custo"
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
    # COM QUE MODELO cada resolver falou. Vazio (`""`) e o resolver que nao
    # escolheu: quem le converte com o padrao de quem esta lendo.
    #
    # Anda junto de `cost_by_resolver` porque sem ele o custo nao e
    # conversivel: `Cost` guarda TOKENS, e os mesmos tokens custam 5x mais em
    # opus que em haiku. Medido contra o Barrier em 2026-09-23, o mesmo run
    # saiu por 541.300 µ¢ na resposta e 2.706.500 µ¢ no store, porque o store
    # reconstruia o modelo de um default. O modelo e um FATO do run; um default
    # na hora de LER e um palpite.
    modelo_por_resolver: dict[str, str] = field(default_factory=dict)
    # Quantas RESOLUÇÕES cada resolver produziu.
    resolved_by_resolver: dict[str, int] = field(default_factory=dict)
    # Quantos ITENS as resoluções de cada resolver consumiram. Campo separado
    # do de cima, e os dois nomes dizem a unidade porque ela não é a mesma:
    # uma resolução de pagamento agregado consome um bancário e três
    # contábeis. Quem quer "que fração do pool esta regra resolveu" precisa
    # DESTE — dividir a contagem de resoluções pelo tamanho do pool dá metade
    # do número na conciliação, e o número certo num domínio de um item por
    # resolução. Uma métrica que muda de significado com o domínio é erro de
    # unidade, e este repositório já pagou por um (ver
    # `MICROCENTS_POR_CENTAVO_BRL`).
    #
    # É a soma de `len(Resolution.item_ids)`, ou seja o que o resolver AFIRMA
    # ter consumido — ver o comentário em `runtime/engine.py`. A lacuna
    # continua saindo de `unresolved`, que é contado.
    resolved_items_by_resolver: dict[str, int] = field(default_factory=dict)
    resolutions_by_class: dict[CostClass, list[Resolution]] = field(default_factory=dict)
    # POR QUE o runtime fez o que fez. Sem isto, uma execução em que a
    # política pulou o agente é indistinguível de uma em que o agente não achou
    # nada — a mesma ambiguidade que `proposals_api_failed` elimina em
    # `agent_eval.py`.
    policy_decisions: tuple[PolicyDecision, ...] = ()
    finished_at: datetime | None = None
    error: str | None = None
    # Quantas vezes a sequência de stages rodou. 1 no caso comum.
    rondas: int = 1
    # Quantos itens este run CRIOU. Zero enquanto o pool só encolhia.
    #
    # Existe porque a conta da borda era `resolvidos = pool_inicial - sobrou`, e
    # ela pressupunha que o pool nunca cresce. Com um bloco que produz — a
    # `entrada` que lê um banco, a `condicao` que roteia — o pool cresce, e a
    # conta dava NEGATIVO: medido, um run que leu 8 pedidos reportou
    # `resolvidos: -7` e lacuna de 800%.
    #
    # Num produto cuja tese é "a lacuna nunca mente", esse é o pior número
    # possível. O denominador honesto é "todo item que existiu neste run", e é
    # isto que o fecha.
    produzidos: int = 0

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
