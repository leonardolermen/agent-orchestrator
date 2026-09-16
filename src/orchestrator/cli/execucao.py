"""A fiação que executa um benchmark: barramento, coletor, motor.

**Por que isto mora na borda e não no domínio.** A primeira versão pôs esta
função em `domains/swe/avaliacao.py` e a catraca de arquitetura reprovou:
`domains -> observability` não está em `PERMITIDO`. A tentação foi relaxar a
tabela; o motivo de não relaxar é o ADR-02 — o barramento é OBSERVAÇÃO, não
controle, e um domínio que instancia o coletor é um domínio que sabe como está
sendo observado. Amanhã ele depende disso, e a observação vira caminho crítico.

Aqui a fiação é genérica: recebe conjunto, braços e vocabulário de abstenção, e
não sabe o que é uma issue nem o que é uma divergência. Vale para `swe`, vale
para conciliação, vale para o próximo domínio — que é o teste de que ela está na
camada certa.
"""

from datetime import UTC, datetime

from orchestrator.agent.llm import LLMClient
from orchestrator.evaluation.benchmark import BenchmarkArm, BenchmarkResult, rodar
from orchestrator.evaluation.case import EvalDataset
from orchestrator.evaluation.waste import EconomiaDeFerramentas, medir_ferramentas
from orchestrator.kernel.event import EventBus
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.observability.collector import SpanCollector
from orchestrator.runtime.engine import execute


def pool_de(dataset: EvalDataset) -> WorkSet:
    """Os itens de todos os casos, como pool executável.

    `WorkSet.__post_init__` recusa ids repetidos, e `EvalDataset.by_item_id`
    recusa o mesmo item em dois casos — as duas guardas cobrem a mesma falha
    por lados diferentes, e é de propósito: esta função é onde elas se
    encontram.
    """
    itens: tuple[WorkItem, ...] = tuple(
        item for caso in dataset.cases for item in caso.input_snapshot
    )
    return WorkSet(items=itens)


def avaliar(
    dataset: EvalDataset,
    arms: tuple[BenchmarkArm, ...],
    client: LLMClient,
    *,
    abstem_com: frozenset[str],
    agora: datetime | None = None,
) -> tuple[BenchmarkResult, dict[str, EconomiaDeFerramentas]]:
    """Roda cada braço com trace e devolve as métricas e a economia por braço.

    Um barramento e um coletor NOVOS por braço. Reaproveitar produziria um
    trace com os spans dos dois misturados, e a economia de ferramenta de um
    apareceria no outro — o tipo de contaminação que faria o braço
    `sem-ferramenta` reportar uso de ferramenta.
    """
    economias: dict[str, EconomiaDeFerramentas] = {}

    def executor(arm: BenchmarkArm, ds: EvalDataset):
        barramento = EventBus()
        coletor = SpanCollector().subscribe(barramento)
        modelo = arm.modelo_efetivo(client.model)
        run = execute(
            arm.workflow,
            pool_de(ds),
            bus=barramento,
            model=modelo,
            input_ref=f"{ds.id}:{arm.label}",
        )
        trace = coletor.trace(run)
        economias[arm.label] = medir_ferramentas(
            trace,
            model=modelo,
            abstiveram=frozenset(
                p.item_id for p in run.proposals if p.tipo in abstem_com
            ),
        )
        return run, trace

    resultado = rodar(
        arms,
        dataset,
        executor,
        model=client.model,
        abstem_com=abstem_com,
        agora=agora or datetime.now(UTC),
    )
    return resultado, economias
