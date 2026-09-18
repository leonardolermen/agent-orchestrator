"""A definição de workflow: o objeto que o motor executa E que a API serializa.

**Zero conhecimento de domínio, desde o PR #5.** Este módulo trazia
`default_definition()` — a cascata de conciliação — e por causa dela importava
o motor (para `default_resolvers`) e o pacote `review` (para o revisor). Eram
quatro das arestas ilegais da CAUSA 2, e a circularidade `engine <-> definition`
que dois imports locais escondiam. A definição PADRÃO é configuração de
produto, não parte do kernel: ela mora em `conciliacao.py`.

Que seja o MESMO objeto nos dois lados é o ponto. Uma definição declarativa
paralela, que descrevesse o que o motor faz, permitiria drift entre o desenho
e a execução — e um desenho que não corresponde ao motor é a decoração que o
§3.5 do spec de composição nomeia como modo de falha.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from orchestrator.kernel.policy import ExecutionPolicy
from orchestrator.kernel.resolver import Resolver


@dataclass(frozen=True)
class Stage:
    name: str
    cascade: tuple[Resolver, ...]
    # Quais `kind` de item este degrau consome. VAZIO = o pool inteiro, que é
    # exatamente o comportamento anterior a esta fatia — e é o que mantém as 9
    # definições existentes sem edição.
    #
    # A CONDICIONAL do kernel mora aqui: um stage cujo `consome` não casa com
    # nada simplesmente não roda. É ausência de item, não predicado, e é por
    # isso que o kernel não ganha linguagem de expressão.
    consome: frozenset[str] = frozenset()
    # Quais `kind` este degrau pode produzir. DECLARADO, não observado:
    # a recusa de beco sem saída, as arestas do canvas e a `version` precisam
    # do grafo ANTES da execução, e um grafo que só existe depois de rodar não
    # previne nada e não desenha nada.
    produz: frozenset[str] = frozenset()
    # A política deste stage. O default reproduz EXATAMENTE o comportamento
    # anterior ao M3: teto na classe mais cara, autonomia PROPOR, sem predicado
    # e sem razão de custo. É por isso que o motor de política entra sem mudar
    # um único número.
    policy: "ExecutionPolicy" = field(default_factory=lambda: ExecutionPolicy())

    def ordered(self) -> list[Resolver]:
        """A cascata na ordem em que roda.

        `sorted` é estável: a ordem entre classes de custo é derivada, a ordem
        dentro de uma classe é a que o autor da definição escreveu.
        """
        return sorted(self.cascade, key=lambda r: r.cost_class)


def consome_de(cascade: Iterable[Resolver]) -> frozenset[str]:
    """A união do que cada resolver da cascata declara consumir.

    Mora aqui, e não em `workflows.py`, por um motivo mecânico e um de
    desenho. O mecânico: `authoring/composicao.py` precisa chamar isto, e
    `workflows.py` importa `authoring/composicao.py` — em `workflows.py` seria
    um ciclo. O de desenho: esta função só lê `Resolver.describe()`; é
    conhecimento de kernel, sem domínio.

    E é uma FUNÇÃO chamada por cada construtor, não uma derivação em
    `Stage.__post_init__`: popular `consome` no kernel trocaria em silêncio o
    significado do default vazio ("vê o pool inteiro") para toda definição
    escrita em Python. Cada construtor decide; o kernel não muda de semântica.
    """
    return frozenset().union(*(r.describe().consome for r in cascade))


def Task(  # noqa: N802 — é um construtor, e o nome é o do conceito
    name: str,
    *,
    resolver: Resolver | None = None,
    cascade: tuple[Resolver, ...] | list[Resolver] | None = None,
    consome: frozenset[str] = frozenset(),
    produz: frozenset[str] = frozenset(),
    policy: ExecutionPolicy | None = None,
) -> Stage:
    """Açúcar: `Task(resolver=x)` é `Stage(cascade=(x,))`.

    NÃO é um conceito novo, e a ausência dele é deliberada. O spec de composição
    §1.2 diz textualmente que passo simples e cascata "não são dois conceitos; é
    um" — criar `Task` como entidade separada duplicaria estado, duplicaria
    serialização e criaria a pergunta "uma task tem stages ou um stage tem
    tasks?", que não tem resposta boa.

    Existe para que quem chega do CrewAI encontre a palavra que espera, sem que
    o kernel ganhe um segundo conceito para manter em sincronia.
    """
    if (resolver is None) == (cascade is None):
        raise ValueError("Task exige `resolver` OU `cascade`, exatamente um")
    return Stage(
        name=name,
        cascade=(resolver,) if resolver else tuple(cascade),
        consome=consome,
        produz=produz,
        policy=policy or ExecutionPolicy(),
    )


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    stages: tuple[Stage, ...]
    # Quantas vezes a sequência de stages pode rodar. 1 = a semântica anterior
    # a esta fatia, EXATA: os stages rodam em ordem e um pipeline fecha numa
    # passada. Ronda extra só é necessária para ARESTA DE VOLTA — o revisor
    # reprova e o rascunho volta ao escritor. A complexidade do laço se paga
    # só quando há laço.
    max_rondas: int = 1
    # Os `kind` que SÃO a saída do run. É a única exceção à recusa de beco sem
    # saída, e existe para que "ninguém consome isto" seja afirmação do autor
    # em vez de acidente.
    entrega: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.max_rondas < 1:
            raise ValueError(f"max_rondas precisa ser pelo menos 1: {self.max_rondas}")
        # Beco sem saída: um item produzido que ninguém consome fica no pool
        # para sempre e nunca chega a um revisor. Falha na CONSTRUÇÃO, e aqui
        # — no kernel — e não em `authoring.construir()`: `construir()` é a via
        # de AUTORIA, e os domínios em Python montam `WorkflowDefinition`
        # direto. Uma guarda que só protege o canvas não protege o código, e é
        # o código que roda em produção.
        #
        # **Um stage com `consome` vazio vê o POOL INTEIRO** — logo consome
        # qualquer kind, e nenhum kind pode ficar órfão. Sem esta saída, a
        # checagem literal contava `consome=frozenset()` como "não consome
        # nada" e RECUSAVA um pipeline correto cujo degrau de baixo usa o
        # default, empurrando o autor a listar kinds INTERMEDIÁRIOS em
        # `entrega` só para conseguir construir — o que transforma a
        # declaração numa mentira E desliga a guarda justo para esses kinds.
        #
        # O CUSTO, dito em voz alta: a guarda fica INERTE no grafo inteiro
        # assim que um único stage usa o default. Um kind digitado errado num
        # grafo assim não é pego aqui. Declarar `consome` em TODOS os stages é
        # o que compra a checagem de volta — e é por isso que os domínios de
        # pipeline declaram. Uma guarda honesta e inerte é melhor que uma que
        # recusa grafo válido e ensina o autor a mentir em `entrega`.
        if any(not s.consome for s in self.stages):
            return
        consumidos: set[str] = set()
        for s in self.stages:
            consumidos |= s.consome
        for s in self.stages:
            orfaos = sorted(s.produz - consumidos - self.entrega)
            if orfaos:
                raise ValueError(
                    f"beco sem saída no stage {s.name!r}: {orfaos} não são "
                    f"consumidos por nenhum stage nem declarados em `entrega`"
                )

    @property
    def version(self) -> str:
        """sha256 curto da FORMA da cascata. Derivado, nunca escrito à mão.

        O spec de composição §4.2 exige "versão imutável, execução fixa a
        versão", e `Run.workflow_version` é onde ela é fixada. Número escrito à
        mão é número que desatualiza em silêncio — a mesma razão de `_param()`
        ler o default do próprio dataclass no catálogo do grill.

        **Limite conhecido, e é real.** A forma é `(id, max_rondas, entrega,
        nome do stage, consome, produz, nome e classe de cada resolver, na
        ordem de execução)` — o GRAFO inteiro, não só a cascata. Dois
        workflows com o mesmo encadeamento de resolvers mas arestas
        diferentes (`consome`/`produz` trocados, ou `max_rondas` diferente)
        são dois grafos diferentes, e não podem colidir na mesma versão.
        Trocar um PARÂMETRO — `L2(max_cents=5)` para `L2(max_cents=20)` — não
        muda a versão, porque o kernel não tem como introspectar parâmetro de
        resolver genericamente. Fechar isso exige `Resolver.version`, que é o
        PR #11 (a mesma peça que a chave de idempotência precisa). Até lá,
        esta versão responde "o grafo mudou de forma?", não "o grafo mudou?".
        """
        forma = [
            self.id,
            self.max_rondas,
            sorted(self.entrega),
            [
                [
                    s.name,
                    sorted(s.consome),
                    sorted(s.produz),
                    [[r.name, int(r.cost_class)] for r in s.ordered()],
                ]
                for s in self.stages
            ],
        ]
        # A POLÍTICA não entra na versão, e é deliberado: ela é variável de
        # EXPERIMENTO (§14.4). Rodar o mesmo workflow com duas políticas tem de
        # produzir a mesma `workflow_version`, ou o benchmark compararia dois
        # workflows em vez de duas políticas. A política vai no `Run`, por
        # `PolicyDecision`, que é onde ela é observável.
        bruto = json.dumps(forma, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:12]
