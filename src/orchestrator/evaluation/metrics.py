"""As métricas de uma execução avaliada. Genéricas — nenhum vocabulário de
domínio entra aqui.

**A diferença para `orchestrator/metrics.py`.** Aquele mede conciliação e diz
`bank_total`, `ledger_total`, `divergent_amount`. É a implementação de
referência e continua valendo — o job `conciliador` do CI depende dela. Este
mede QUALQUER execução contra QUALQUER conjunto de casos, e por isso não pode
saber o que é um lançamento bancário.

**A métrica que o produto precisa e que não existia.**
`microcents_per_correct_proposal`. Um modelo com metade do preço e metade da
precisão **não** é mais barato: ele produz metade das propostas certas pelo
mesmo dinheiro por proposta certa, e gasta o dobro de revisão humana com o
resto. Custo por item esconde isso; custo por proposta CORRETA não.

**O que este módulo se recusa a fazer.** Não inventa número que não mediu. Se
não há trace, `p50_latency_ms` é `None` e não zero — a mesma disciplina de
`EvalResult.custo_medido` e do renderizador, que deixa a coluna vazia em vez de
imprimir `US$ 0,0000`.
"""

from dataclasses import dataclass
from statistics import quantiles

from orchestrator.evaluation.case import EvalDataset
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import TraceKind
from orchestrator.kernel.run import Run
from orchestrator.kernel.trace import SpanKind, Trace


@dataclass(frozen=True)
class EvalMetrics:
    """O resultado de pontuar um `Run` contra um `EvalDataset`."""

    dataset_version: str
    items_total: int

    # -- qualidade --------------------------------------------------------
    deterministic_rate: float
    resolution_rate: float
    # SOBREPOSIÇÃO e CONTENÇÃO TOTAL na conciliação (decisão 24), aqui na forma
    # genérica: um falso positivo é uma resolução determinística que o esperado
    # diz que NÃO deveria ter acontecido — o sistema afirmou algo falso. Um
    # falso negativo é o contrário: deveria ter fechado de graça e não fechou.
    #
    # A assimetria de gravidade é a mesma: o falso negativo custa um agente; o
    # falso positivo fecha errado e ninguém olha. Por isso só ele está em
    # `zero_tolerance` no `RegressionCheck`.
    false_positives: int
    false_negatives: int
    proposal_precision: float
    abstention_rate: float

    # -- custo ------------------------------------------------------------
    microcents_total: int
    microcents_per_item: int
    # `None`, e não zero, quando nenhuma proposta correta foi produzida: a
    # divisão não existe, e zero se leria como "de graça".
    microcents_per_correct_proposal: int | None

    # -- operação ---------------------------------------------------------
    escalation_rate: float
    api_failures: int
    proposals_total: int
    proposals_correct: int
    proposals_abstained: int
    p50_latency_ms: int | None = None
    p95_latency_ms: int | None = None

    def render(self) -> str:
        linhas = [
            f"dataset:                       {self.dataset_version} "
            f"({self.items_total} itens)",
            f"Taxa determinística:           {100 * self.deterministic_rate:.1f}%",
            f"Taxa de resolução:             {100 * self.resolution_rate:.1f}%",
            f"Falsos positivos:              {self.false_positives}",
            f"Falsos negativos:              {self.false_negatives}",
            f"Propostas:                     {self.proposals_total} "
            f"({self.proposals_correct} corretas, "
            f"{self.proposals_abstained} abstenções)",
            f"Precisão (das que arriscaram): {100 * self.proposal_precision:.1f}%",
            f"Taxa de abstenção:             {100 * self.abstention_rate:.1f}%",
            f"Taxa de escalada (humano):     {100 * self.escalation_rate:.1f}%",
            f"Custo total:                   "
            f"US$ {self.microcents_total / 100_000_000:.4f}",
            f"Custo por item:                "
            f"US$ {self.microcents_per_item / 100_000_000:.6f}",
        ]
        if self.microcents_per_correct_proposal is None:
            linhas.append(
                "Custo por proposta CORRETA:    não definido — nenhuma proposta "
                "correta foi produzida"
            )
        else:
            linhas.append(
                f"Custo por proposta CORRETA:    "
                f"US$ {self.microcents_per_correct_proposal / 100_000_000:.6f}"
            )
        if self.p50_latency_ms is not None:
            linhas.append(f"Latência por item p50/p95:     "
                          f"{self.p50_latency_ms}ms / {self.p95_latency_ms}ms")
        if self.api_failures:
            linhas.append(
                f"ATENÇÃO — falha de API em {self.api_failures} investigações; "
                f"os números acima cobrem apenas as restantes."
            )
        return "\n".join(linhas)


def _latencias(trace: Trace | None) -> tuple[int | None, int | None]:
    if trace is None:
        return None, None
    duracoes = sorted(
        s.duration_ms
        for s in trace.spans
        if s.kind is SpanKind.ITEM and s.duration_ms
    )
    if not duracoes:
        return None, None
    if len(duracoes) < 2:
        return duracoes[0], duracoes[0]
    # `n=100` dá percentis; o índice 49 é o p50 e o 94 é o p95.
    centis = quantiles(duracoes, n=100, method="inclusive")
    return int(centis[49]), int(centis[94])


def medir(
    run: Run,
    dataset: EvalDataset,
    *,
    model: str,
    abstem_com: frozenset[str],
    trace: Trace | None = None,
) -> EvalMetrics:
    """Pontua um `Run` contra um conjunto de casos.

    Não executa nada e não conhece `runtime` — recebe o run pronto. É o que
    permite `evaluation` viver numa camada que não pode importar o motor, e é
    também o que permite pontuar um run LIDO DO DISCO meses depois.

    `abstem_com` são os valores de `Proposal.tipo` que significam "não sei"
    NESTE domínio — `NAO_IDENTIFICADO` na conciliação, `DUVIDA` no `swe`.
    Parâmetro obrigatório de propósito: `orchestrator/metrics.py` resolve a
    mesma pergunta comparando contra `DivergenceType.NAO_IDENTIFICADO`, e essa
    linha é a violação `metrics -> taxonomy` que a catraca lista. Passar o
    vocabulário para dentro faria a camada genérica herdar o mesmo defeito;
    exigi-lo na chamada deixa o acoplamento visível onde ele é legítimo — na
    fronteira do domínio.
    """
    por_item = dataset.by_item_id()

    # A INVARIANTE que custou um terço de um conjunto de avaliação.
    #
    # Se um valor significa ao mesmo tempo "não consegui classificar" e "este é
    # o tipo certo", os casos com esse tipo esperado saem do denominador da
    # precisão e entram na taxa de abstenção. Medido no `swe` em 2026-09-16:
    # `DUVIDA` era as duas coisas, 16 dos 50 casos tinham `DUVIDA` como tipo
    # esperado, e a taxa de abstenção reportada (32%) era exatamente a fatia de
    # DUVIDA do conjunto. Nenhum número absoluto valia.
    #
    # Levanta em vez de avisar: um relatório que roda e sai errado é pior que
    # um que não roda, porque alguém o lê.
    colisao = sorted(
        abstem_com & {c.expected.kind for c in dataset.cases if c.expected.kind}
    )
    if colisao:
        raise ValueError(
            f"{colisao} é rótulo de abstenção E tipo esperado no dataset "
            f"{dataset.id!r}. Os casos com esse tipo sairiam do denominador da "
            f"precisão e entrariam na taxa de abstenção — o conjunto perderia "
            f"{len([c for c in dataset.cases if c.expected.kind in colisao])} "
            f"de {len(dataset.cases)} casos sem nada denunciar. Separe o "
            f"rótulo de 'não sei' do vocabulário de tipos do domínio"
        )

    total = len(por_item)
    if total == 0:
        raise ValueError(
            f"dataset {dataset.id!r} não tem item nenhum; toda taxa abaixo "
            f"seria uma divisão por zero disfarçada de 0%"
        )

    # -- resolução ---------------------------------------------------------
    resolvidos: set[str] = set()
    deterministicos: set[str] = set()
    for classe, resolucoes in run.resolutions_by_class.items():
        for r in resolucoes:
            alvos = {i for i in r.item_ids if i in por_item}
            resolvidos |= alvos
            if classe is CostClass.REGRA:
                deterministicos |= alvos
    escalados = {
        i
        for classe, rs in run.resolutions_by_class.items()
        if classe is CostClass.HUMANO
        for r in rs
        for i in r.item_ids
        if i in por_item
    }

    falsos_positivos = sum(
        1
        for item_id in deterministicos
        if not por_item[item_id].expected.should_resolve_deterministically
    )
    falsos_negativos = sum(
        1
        for item_id, caso in por_item.items()
        if caso.expected.should_resolve_deterministically
        and item_id not in deterministicos
    )

    # -- propostas ---------------------------------------------------------
    # Uma proposta sem `kind` esperado NÃO conta como erro: ninguém estabeleceu
    # a verdade dela. Contá-la como errada puniria o agente por um caso que o
    # dataset não sabe pontuar — e faria a precisão cair ao colher casos de
    # REJEITAR, que é exatamente quando ela deveria subir.
    propostas = [p for p in run.proposals if p.item_id in por_item]
    abstencoes = sum(1 for p in propostas if p.tipo in abstem_com)
    arriscadas = [p for p in propostas if p.tipo not in abstem_com]
    julgaveis = [p for p in arriscadas if por_item[p.item_id].expected.kind is not None]
    corretas = sum(
        1 for p in julgaveis if p.tipo == por_item[p.item_id].expected.kind
    )

    falhas_api = sum(
        1
        for p in run.proposals
        if any(e.kind is TraceKind.ERRO for e in p.trace)
    )

    # -- custo -------------------------------------------------------------
    microcents = run.cost_total().microcents(model)
    p50, p95 = _latencias(trace)

    return EvalMetrics(
        dataset_version=dataset.version,
        items_total=total,
        deterministic_rate=len(deterministicos) / total,
        resolution_rate=len(resolvidos) / total,
        false_positives=falsos_positivos,
        false_negatives=falsos_negativos,
        proposal_precision=(corretas / len(julgaveis)) if julgaveis else 0.0,
        abstention_rate=(abstencoes / len(propostas)) if propostas else 0.0,
        microcents_total=microcents,
        microcents_per_item=microcents // total,
        microcents_per_correct_proposal=(microcents // corretas) if corretas else None,
        escalation_rate=len(escalados) / total,
        api_failures=falhas_api,
        proposals_total=len(propostas),
        proposals_correct=corretas,
        proposals_abstained=abstencoes,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
    )
