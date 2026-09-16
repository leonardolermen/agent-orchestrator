"""Modelo canônico de conciliação, e a ponte dele com o kernel.

Cardinalidade: uma resolução vincula conjuntos a conjuntos, nunca par a par.
Exigido por PAGAMENTO_AGREGADO (1 crédito : N notas) e DEVOLUCAO_FUNDOS
(cadeia de 2-3 lançamentos bancários para 1 contábil). Ver spec 4.5.

Todos os valores monetários são int em centavos. Débitos bancários são
negativos, créditos positivos.

**A ponte.** O kernel não sabe o que é "lado". Ele move `WorkItem` com um
`kind` opaco e `Resolution` com um `item_ids` só. A noção de lado bancário e
lado contábil — e a regra de cardinalidade que vem dela — vive AQUI, nos
acessores tipados do fim deste módulo. Eles são o único lugar do domínio que
traduz entre os dois vocabulários, e é por isso que os resolvers não precisam
fazer `isinstance` em lugar nenhum.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from orchestrator.kernel.cost import Cost
from orchestrator.kernel.resolution import Proposal, Resolution, TraceEvent
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.taxonomy import DivergenceType


@dataclass(frozen=True)
class BankEntry:
    """Lançamento de extrato bancário."""

    id: str
    date: date
    amount: int
    description: str
    counterparty: str | None = None
    document: str | None = None


@dataclass(frozen=True)
class LedgerEntry:
    """Lançamento contábil."""

    id: str
    accrual_date: date
    cash_date: date | None
    gross_amount: int
    net_amount: int
    account: str
    supplier: str
    cost_center: str | None = None
    document: str | None = None


@dataclass(frozen=True)
class Divergence:
    """O que nenhuma camada determinística resolveu."""

    id: str
    bank_ids: frozenset[str]
    ledger_ids: frozenset[str]

    def __post_init__(self) -> None:
        # Ao contrário de MatchResult, um lado vazio aqui é válido: um
        # lançamento contábil sem contrapartida bancária (ou vice-versa) é
        # uma divergência legítima de um lado só. Os dois vazios é que não
        # descrevem nada — nem um vínculo, nem uma sobra.
        if not self.bank_ids and not self.ledger_ids:
            raise ValueError("Divergence precisa de pelo menos um id")


# ---------------------------------------------------------------------------
# A ponte entre o domínio e o kernel.
#
# Estas seis funções são o único lugar que sabe, ao mesmo tempo, o que é um
# lançamento bancário e o que é um `WorkItem`. Concentrá-las aqui é o que
# permite que `kernel/` não conheça conciliação e que os resolvers não
# conheçam `WorkItem`.
# ---------------------------------------------------------------------------

BANCO = "banco"
CONTABIL = "contabil"


def pool(bank: list[BankEntry], ledger: list[LedgerEntry]) -> WorkSet:
    """O `WorkSet` inicial de uma conciliação.

    Banco PRIMEIRO, contábil depois, e a ordem importa: `divergencias()`
    percorre `items` na ordem, e o golden de 12 sementes pina a ordem em que as
    divergências saem. Trocar as duas linhas abaixo muda o golden.

    **A disjunção dos ids é garantida aqui, de graça.** Com `Resolution.item_ids`
    unificado, `metrics` separa lado intersectando com os ids de cada lado — o
    que só está correto se nenhum id bancário for igual a um contábil. Antes
    isso era suposição (o gerador usa prefixos `b`/`l`); agora é invariante:
    os dois lados entram no MESMO `WorkSet`, e `WorkSet.__post_init__` recusa
    id repetido. Uma colisão levanta aqui, na construção, em vez de virar
    métrica errada lá na frente.
    """
    return WorkSet(
        items=tuple(WorkItem(id=e.id, kind=BANCO, payload=e) for e in bank)
        + tuple(WorkItem(id=e.id, kind=CONTABIL, payload=e) for e in ledger)
    )


def banco(work: WorkSet) -> list[BankEntry]:
    """Os lançamentos bancários ainda não resolvidos, tipados."""
    return list(work.payloads(BANCO))


def contabil(work: WorkSet) -> list[LedgerEntry]:
    """Os lançamentos contábeis ainda não resolvidos, tipados."""
    return list(work.payloads(CONTABIL))


def divergencias(work: WorkSet) -> list[Divergence]:
    """Uma divergência por lançamento órfão, banco primeiro.

    Era `WorkSet.as_divergences()`. Vem para o domínio inteira, sem mudança de
    ordem nem de formato de id, porque o agente recebe exatamente esta lista e
    o golden a pina indiretamente.
    """
    return [
        Divergence(
            id=f"d-b-{i.id}", bank_ids=frozenset({i.id}), ledger_ids=frozenset()
        )
        for i in work.of_kind(BANCO)
    ] + [
        Divergence(
            id=f"d-l-{i.id}", bank_ids=frozenset(), ledger_ids=frozenset({i.id})
        )
        for i in work.of_kind(CONTABIL)
    ]


def conciliacao(
    work: WorkSet,
    item_ids: frozenset[str],
    produced_by: str,
    rule: str,
    evidence: dict[str, Any] | None = None,
) -> Resolution:
    """Uma `Resolution` de conciliação, com as duas guardas do domínio.

    Recebe o POOL, e não os dois lados já separados pelo chamador, e a
    diferença é o ponto desta função.

    **Guarda 1 — cardinalidade.** `MatchResult.__post_init__` exigia pelo menos
    um id de cada lado. `Resolution` não pode exigir isso (um domínio de um
    lado só é legítimo), então a regra desce para cá, que é onde "lado"
    significa alguma coisa.

    **Guarda 2 — o lado vem do POOL, nunca do chamador.** `revisor.py` já
    tomava esse cuidado por disciplina ("o lado de cada id vem do POOL, nunca
    do prefixo do id"). Aqui ele deixa de ser disciplina: com `item_ids`
    unificado, um chamador que trocasse os dois lados produziria exatamente a
    mesma `Resolution`, e nenhum teste conseguiria notar. Derivando o lado
    aqui, a troca deixa de ser expressável.

    De brinde, `item_ids` que não estão no pool viram erro na CONSTRUÇÃO. É a
    guarda contra id fantasma que hoje só existe em `metrics.evaluate` — ali
    ela protege a métrica; aqui protege o estado.
    """
    banco_ids, contabil_ids = lados(work, item_ids)
    fantasmas = sorted(item_ids - (banco_ids | contabil_ids))
    if fantasmas:
        raise ValueError(
            f"{produced_by} citou ids que não estão no pool: {fantasmas}"
        )
    if not banco_ids or not contabil_ids:
        raise ValueError(
            f"{produced_by}: conciliação exige pelo menos um id de cada lado "
            f"(banco={sorted(banco_ids)}, contábil={sorted(contabil_ids)})"
        )
    return Resolution(
        item_ids=frozenset(item_ids),
        produced_by=produced_by,
        rule=rule,
        evidence=evidence or {},
    )


def lados(work: WorkSet, ids: frozenset[str]) -> tuple[frozenset[str], frozenset[str]]:
    """Separa ids por lado, consultando o POOL.

    Nunca por prefixo do id nem por convenção de nome: o revisor humano já
    tomava esse cuidado (`revisor.py`, "o lado de cada id vem do POOL, nunca do
    prefixo"), e agora ele é a única forma possível — o kernel não guarda lado.

    Ids que não estão no pool não aparecem em nenhum dos dois conjuntos. Quem
    chama decide se isso é obsolescência ou erro.
    """
    por_id = {i.id: i.kind for i in work.items}
    return (
        frozenset(i for i in ids if por_id.get(i) == BANCO),
        frozenset(i for i in ids if por_id.get(i) == CONTABIL),
    )


def abstencao(
    item_id: str,
    motivo: str,
    cost: "Cost | None" = None,
    trace: "list[TraceEvent] | None" = None,
) -> Proposal:
    """O "não sei" da conciliação.

    `Proposal.abstencao` passou a exigir o `tipo` quando a proposta virou
    genérica (PR #6): qual é o rótulo de não-saber é decisão do domínio, e o
    kernel não pode ter `NAO_IDENTIFICADO` embutido.

    Esta função existe para que essa generalização não custe um
    `DivergenceType.NAO_IDENTIFICADO` repetido em cada uma das oito chamadas.
    A repetição seria a mesma classe de join frágil que o `CATALOGO` do grill
    já evita: oito lugares que precisam concordar sobre qual é o não-sei.
    """
    return Proposal.abstencao(
        item_id, DivergenceType.NAO_IDENTIFICADO, motivo, cost, trace
    )
