"""Comparar variantes: fixar o dataset, variar UM braço, medir.

**A propriedade que torna isto barato.** Um `BenchmarkArm` carrega uma
`WorkflowDefinition` e uma `ExecutionPolicy`, ambas dataclasses congelados e
serializáveis. Comparar duas cascatas é construir duas definições e rodar o
mesmo conjunto — não há modo de avaliação, não há flag no motor, e o runtime
não sabe que está sendo avaliado. É a diferença entre avaliação como FEATURE do
runtime (que contamina o caminho de produção) e avaliação como composição de
peças que já existem.

**Por que o executor é injetado.** `PERMITIDO["evaluation"]` é
`{kernel, storage, observability}` — esta camada não pode importar `runtime`.
Isso não é obstáculo, é o desenho: a avaliação PONTUA execuções, não as produz.
Quem executa é a borda (CLI, API), que pode alcançar tudo. O efeito colateral é
bom: dá para avaliar um run lido do disco, um run de produção, ou um run de um
motor que ainda não existe, sem tocar nesta camada.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from orchestrator.kernel.definition import WorkflowDefinition
from orchestrator.kernel.policy import ExecutionPolicy
from orchestrator.kernel.run import Run
from orchestrator.kernel.trace import Trace

from orchestrator.evaluation.case import EvalDataset
from orchestrator.evaluation.metrics import EvalMetrics, medir


@dataclass(frozen=True)
class BenchmarkArm:
    """Uma variante a comparar. É aqui que "sem contaminar o runtime" mora.

    `model` é `None` quando o braço não varia o modelo — e aí o modelo vem do
    benchmark. Um braço que fixasse o modelo sempre obrigaria quem compara
    POLÍTICAS a repetir o mesmo modelo em todos os braços, e a primeira vez que
    alguém esquecesse produziria uma comparação de política contaminada por
    modelo, sem sintoma.
    """

    label: str
    workflow: WorkflowDefinition
    policy: ExecutionPolicy | None = None
    model: str | None = None

    def modelo_efetivo(self, padrao: str) -> str:
        return self.model or padrao


@dataclass(frozen=True)
class BenchmarkResult:
    """O que cada braço mediu, com a versão do conjunto que mediu.

    `dataset_version` não é decoração: dois resultados só são comparáveis se
    mediram o mesmo conjunto, e sem a versão gravada junto nada impede alguém
    de comparar o resultado de hoje com o de antes de colher duzentos casos —
    e concluir que o modelo piorou quando o que mudou foi a prova.
    """

    dataset_id: str
    dataset_version: str
    at: datetime
    arms: tuple[tuple[BenchmarkArm, EvalMetrics], ...] = ()

    def por_label(self) -> dict[str, EvalMetrics]:
        return {arm.label: m for arm, m in self.arms}

    def melhor_por_custo_efetivo(self) -> tuple[BenchmarkArm, EvalMetrics] | None:
        """O braço com o menor custo POR PROPOSTA CORRETA.

        Não é o mais barato: é o que entrega acerto mais barato. Braço que não
        produziu proposta correta nenhuma não concorre — ele tem custo por
        acerto indefinido, e tratá-lo como zero o faria vencer sempre.
        """
        candidatos = [
            (a, m) for a, m in self.arms if m.microcents_per_correct_proposal is not None
        ]
        if not candidatos:
            return None
        return min(candidatos, key=lambda par: par[1].microcents_per_correct_proposal)

    def render(self) -> str:
        if not self.arms:
            return "(benchmark sem braço)"
        cab = (
            f"{'braço':<22} {'precisão':>9} {'abst.':>7} {'FP':>4} {'FN':>4} "
            f"{'US$ total':>11} {'US$/acerto':>12}"
        )
        linhas = [
            f"dataset {self.dataset_id} @ {self.dataset_version}",
            "",
            cab,
            "-" * len(cab),
        ]
        for arm, m in self.arms:
            por_acerto = (
                "—"
                if m.microcents_per_correct_proposal is None
                else f"{m.microcents_per_correct_proposal / 100_000_000:.6f}"
            )
            linhas.append(
                f"{arm.label:<22} {100 * m.proposal_precision:>8.1f}% "
                f"{100 * m.abstention_rate:>6.1f}% "
                f"{m.false_positives:>4} {m.false_negatives:>4} "
                f"{m.microcents_total / 100_000_000:>11.4f} {por_acerto:>12}"
            )
        melhor = self.melhor_por_custo_efetivo()
        if melhor and len(self.arms) > 1:
            linhas += ["", f"menor custo por acerto: {melhor[0].label}"]
        return "\n".join(linhas)


# O que a borda fornece: rodar um braço sobre um conjunto e devolver o run (e,
# quando houver, o trace). Assinatura mínima de propósito — quanto mais ela
# pedisse, mais desta camada vazaria para quem a implementa.
Executor = Callable[[BenchmarkArm, EvalDataset], tuple[Run, Trace | None]]


def rodar(
    arms: tuple[BenchmarkArm, ...],
    dataset: EvalDataset,
    executor: Executor,
    *,
    model: str,
    abstem_com: frozenset[str],
    agora: datetime,
) -> BenchmarkResult:
    """Roda cada braço sobre o MESMO conjunto e pontua os dois igual.

    A guarda de contaminação é aplicada aqui, uma vez, antes do primeiro braço:
    aplicá-la por braço permitiria que dois braços fossem medidos contra
    conjuntos diferentes se seus runs começassem em instantes diferentes — e a
    comparação entre eles deixaria de significar alguma coisa.
    """
    if not arms:
        raise ValueError("benchmark sem braço: não há o que comparar")
    rotulos = [a.label for a in arms]
    if len(set(rotulos)) != len(rotulos):
        raise ValueError(
            f"braços com rótulo repetido: {rotulos}. a tabela de resultado é "
            f"indexada por rótulo, e dois iguais esconderiam um dos dois"
        )

    medidos: list[tuple[BenchmarkArm, EvalMetrics]] = []
    for arm in arms:
        run, trace = executor(arm, dataset)
        # Só os casos que já existiam quando o run começou. Sem isto o
        # benchmark mediria memorização — ver §14.3.
        elegiveis = dataset.elegiveis_para(run.started_at)
        if not elegiveis.cases:
            raise ValueError(
                f"braço {arm.label!r}: nenhum caso é anterior ao run "
                f"({run.started_at.isoformat()}). Todos os casos foram criados "
                f"depois, então medi-los aqui seria medir memorização"
            )
        medidos.append(
            (
                arm,
                medir(
                    run,
                    elegiveis,
                    model=arm.modelo_efetivo(model),
                    abstem_com=abstem_com,
                    trace=trace,
                ),
            )
        )
    return BenchmarkResult(
        dataset_id=dataset.id,
        dataset_version=dataset.version,
        at=agora,
        arms=tuple(medidos),
    )
