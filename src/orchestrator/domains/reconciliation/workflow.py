"""O workflow de conciliação: a cascata padrão e a porta que todo mundo usa.

Este módulo existe para quebrar uma circularidade. Até o PR #5,
`default_resolvers()` morava no motor e `default_definition()` morava na
definição — e as duas se importavam, com dois imports locais escondendo isso do
interpretador. A causa era de camada, não de código: **a cascata padrão é
configuração de produto, não parte do motor nem do kernel.**

Aqui é o único lugar que pode conhecer os dois lados. É a camada `domains`, que
importa runtime, agent e human à vontade — e da qual ninguém importa.

Com a conciliação rebaixada a implementação de referência (§1.3 do spec de
migração), este arquivo é também o EXEMPLO de como um domínio se pluga no
runtime. `domains/procurement` e `domains/swe` (PR #6) têm exatamente esta
forma, com ~80 linhas cada.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orchestrator.domains.reconciliation.models import (
    BANCO,
    CONTABIL,
    BankEntry,
    Divergence,
    LedgerEntry,
    divergencias,
    pool,
)
from orchestrator.domains.reconciliation.politica import POLITICA_ATUAL, contexto
from orchestrator.domains.reconciliation.resolvers.grouping import GroupingMatcher
from orchestrator.domains.reconciliation.resolvers.tolerance import ToleranceMatcher
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition, consome_de
from orchestrator.kernel.event import EventBus
from orchestrator.kernel.policy import ExecutionPolicy, PolicyContext
from orchestrator.kernel.resolution import Proposal, Resolution
from orchestrator.kernel.resolver import Resolver
from orchestrator.kernel.run import Run
from orchestrator.regras import Igualdade
from orchestrator.runtime.engine import execute

if TYPE_CHECKING:
    from orchestrator.review.fila import Fila


@dataclass(frozen=True)
class ReconcileResult:
    """O resultado de uma conciliação, na forma que a CLI, a API e as métricas
    já consomem.

    É o `Run` do motor com o resto do pool traduzido para `Divergence`. Os
    nomes dos campos são os antigos de propósito: este PR move o motor de lugar
    e quebra a circularidade; renomear `matches` para `resolutions` aqui
    obrigaria a tocar `metrics.py`, `api/app.py`, `grill/cli.py` e uma dezena de
    testes para um tipo que o PR #7 substitui por `Run`.
    """

    matches: list[Resolution]
    divergences: list[Divergence]
    proposals: list[Proposal] = field(default_factory=list)
    cost_by_resolver: dict[str, Cost] = field(default_factory=dict)
    matches_by_resolver: dict[str, int] = field(default_factory=dict)
    matches_by_class: dict[CostClass, list[Resolution]] = field(default_factory=dict)
    # O `Run` cru, para quem quiser id, estado, duração e custo total. Os
    # campos acima são a projeção que a CLI, a API e as métricas já consomem;
    # este é o objeto de verdade. Eles somem quando o último chamador migrar.
    run: "Run | None" = None


def l1_exato() -> Resolver:
    """O L1, montado com a regra GENÉRICA de igualdade.

    Era `ExactMatcher`, uma classe própria que lia `be.document` e
    `le.net_amount` porque conhecia os dois tipos. Não havia nada de conciliação
    na lógica dela — indexar um lado pela chave, varrer o outro, primeiro livre
    ganha —, só nos nomes dos campos. Agora os nomes vêm daqui, que é o lugar
    que sabe como os dois lados chamam as coisas, e a lógica vem de `regras/`.

    `modulo=("amount",)` é a única sutileza, e ela é de DADO e não de regra: o
    banco registra saída como negativa e o contábil registra o mesmo valor como
    positivo, então os dois coincidem em magnitude. Era um `abs()` escondido no
    meio da chave do `ExactMatcher` — e era também a razão de ele não poder ser
    genérico.

    O nome continua `"L1"`: `matches_by_layer` entra no golden de 12 sementes, e
    o relatório da CLI é lido por gente que aprendeu a chamar assim.
    """
    return Igualdade(
        esquerda=BANCO,
        direita=CONTABIL,
        campos=("document", "amount=net_amount", "date=cash_date"),
        modulo=("amount",),
        name="L1",
        resumo="documento, valor e data coincidem exatamente",
    )


def default_resolvers() -> list[Resolver]:
    """As três regras, da mais barata para a mais cara dentro da classe.

    Só o L1 é genérico hoje, e a assimetria é informação, não pendência
    esquecida. O L2 mede prazo em DIAS ÚTEIS do calendário bancário brasileiro
    e o L3 trata "crédito é recebimento" como verdade sobre o sinal do valor:
    nenhum dos dois é configuração de campo, os dois são conhecimento sobre o
    negócio. `regras/tolerancia.py` generaliza a FORMA do L2 (chave exata mais
    folga) sem conseguir substituí-lo, e o docstring de lá diz por quê.
    """
    return [l1_exato(), ToleranceMatcher(), GroupingMatcher()]


def default_definition(
    fila: "Fila | None" = None, policy: ExecutionPolicy | None = None
) -> WorkflowDefinition:
    """O conciliador: três regras e o revisor humano.

    Sem agente — ele é opcional, custa dinheiro, e a definição que a API serve
    precisa ser executável sem gastar um centavo.

    O revisor entra SEMPRE. Sem fila ele usa uma vazia e não emite nada, então
    a CLI e o golden ficam idênticos; com fila, ele aplica o que foi aprovado.
    Não há "definição servida" separada da "definição executada".

    Os imports de `review` deixaram de ser locais: aqui eles não são
    circulares, porque `domains` pode importar `human`. Eram locais só enquanto
    esta função morava no kernel.
    """
    from orchestrator.domains.reconciliation.revisor import RevisorHumano
    from orchestrator.review.fila import Fila

    revisor = RevisorHumano(fila=fila if fila is not None else Fila.vazia())
    cascata = (*default_resolvers(), revisor)
    return WorkflowDefinition(
        id="conciliacao",
        name="Conciliação bancária",
        stages=(
            Stage(
                name="conciliar lançamentos",
                cascade=cascata,
                consome=consome_de(cascata),
                policy=policy or POLITICA_ATUAL,
            ),
        ),
    )


def reconcile(
    bank: list[BankEntry],
    ledger: list[LedgerEntry],
    definition: WorkflowDefinition | None = None,
    *,
    bus: "EventBus | None" = None,
    input_ref: str = "",
    policy: "PolicyContext | None" = None,
    model: str = "claude-opus-5",
) -> ReconcileResult:
    """Concilia um extrato contra um razão. A porta de entrada do domínio.

    Continua puro: só LÊ. Quem grava proposta é o CLI e quem grava decisão é a
    API — e é disso que o golden e o teste de "nenhum endpoint gasta dinheiro"
    dependem.

    O `definition=None` que cai para a cascata padrão mora AQUI, e não no motor.
    É a diferença que quebra a circularidade: `execute()` exige a definição, e
    quem tem um padrão é quem conhece o domínio.
    """
    definicao = default_definition() if definition is None else definition
    run = execute(
        definicao,
        pool(bank, ledger),
        bus=bus,
        input_ref=input_ref,
        # O contexto traz `valor_em_risco` e `custo_estimado` — o que o kernel
        # não sabe e o domínio sabe. Sem ele, a regra 7 simplesmente não se
        # aplica, que é o comportamento certo para quem não passou nada.
        policy=policy or contexto(model),
        model=model,
    )
    return ReconcileResult(
        matches=list(run.resolutions),
        divergences=divergencias(run.unresolved),
        proposals=list(run.proposals),
        cost_by_resolver=run.cost_by_resolver,
        matches_by_resolver=run.resolved_by_resolver,
        matches_by_class=run.resolutions_by_class,
        run=run,
    )
