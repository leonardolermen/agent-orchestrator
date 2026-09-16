"""O que um resolver produziu: uma resolução que RESOLVE, ou uma proposta que não.

`Resolution` substitui `MatchResult`. A mudança de fundo é um campo: onde havia
`bank_ids` e `ledger_ids` — dois lados, porque conciliação tem dois lados — há
`item_ids`, um conjunto só.

O lado de cada id continua existindo; ele só deixou de morar aqui. Quem precisa
saber de que lado um id está pergunta ao `WorkSet`, que é quem sabe o `kind` de
cada item. Manter dois campos no kernel seria manter conciliação no kernel, e
um domínio de um lado só (`domains/swe`) teria de preencher um dos dois com
`frozenset()` para sempre.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from orchestrator.kernel.cost import Cost


@dataclass(frozen=True)
class Resolution:
    """Um vínculo que resolve: os itens citados saem do pool.

    Contrapõe-se a `Proposal`, que explica e sugere mas nunca resolve. Os dois
    são tipos SEPARADOS e é deliberado — ver `ResolverOutput`: unificá-los num
    tipo só com um campo de status transformaria uma garantia de tipo numa
    convenção verificada, e um filtro esquecido viraria conciliação fantasma.
    """

    item_ids: frozenset[str]
    # Quem produziu. Era `layer` — palavra do domínio de conciliação, onde as
    # regras se chamam L1/L2/L3. `produced_by` diz a mesma coisa sem supor que
    # resolvers sejam camadas.
    #
    # Continua sendo PROVENIÊNCIA, não identidade do resolver na cascata. Os
    # dois coincidem hoje porque cada resolver estampa o próprio nome, mas são
    # conceitos diferentes por desenho — ver P3.2 em DECISOES.md, que já custou
    # uma correção.
    produced_by: str
    rule: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Resolução sem id não resolve nada e encolheria o pool em zero,
        # passando por trabalho feito. `MatchResult` exigia pelo menos um id de
        # CADA lado; a versão genérica não pode exigir isso (um domínio de um
        # lado só é legítimo), mas pode exigir que exista alguma coisa.
        #
        # A regra de cardinalidade do domínio — conciliação precisa de pelo
        # menos um id de cada lado — não sumiu: ela desce para o domínio, onde
        # a noção de "lado" existe. Ver `models.resolucao_de_conciliacao`.
        if not self.item_ids:
            raise ValueError("Resolution exige pelo menos um id")


class Confidence(StrEnum):
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"



class TraceKind(StrEnum):
    """Os cinco tipos de passo que aparecem no rastro de uma investigação."""

    ENTRADA = "entrada"
    ERRO = "erro"
    LLM = "llm"
    TOOL = "tool"
    OUTCOME = "outcome"


@dataclass(frozen=True)
class TraceEvent:
    """Um passo do que aconteceu ao investigar uma divergência.

    O spec seção 7 exige poder reconstruir por que o sistema chegou a uma
    conclusão. Num produto que um contador vai auditar, uma proposta sem
    rastro é uma afirmação sem fonte.
    """

    kind: TraceKind
    detail: dict[str, Any]


@dataclass(frozen=True)
class Proposal:
    """O que o agente propõe para uma divergência.

    Uma proposta NÃO resolve a divergência. Ela explica e sugere; quem resolve
    é o humano ao aprovar.
    """

    divergence_id: str
    tipo: str
    explicacao: str
    evidencia: list[str]
    confianca: Confidence
    acao_sugerida: str
    cost: Cost = field(default_factory=Cost.zero)
    trace: list[TraceEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        # `confianca` é coagida aqui porque `Confidence` é do kernel: uma
        # string crua vinda de JSON passaria batido pelo guard de evidência
        # logo abaixo, que compara por identidade.
        #
        # `tipo` NÃO é coagido, e é a diferença que torna esta classe genérica:
        # o vocabulário de tipos é do domínio. Quem constrói uma proposta de
        # conciliação já coage explicitamente na fronteira — `interpretar_
        # proposta` faz `DivergenceType(...)` e `serial.proposta_de_dict`
        # também. Como `DivergenceType` é `StrEnum`, o valor coagido É um
        # `str`, e as comparações por identidade (`p.tipo is
        # DivergenceType.X`, P2.6) continuam válidas sem o kernel conhecer a
        # taxonomia.
        object.__setattr__(self, "confianca", Confidence(self.confianca))

        # Confiança alta sem evidência é a combinação que destrói a
        # credibilidade do produto mais rápido que qualquer erro.
        if self.confianca is Confidence.ALTA and not self.evidencia:
            raise ValueError(
                f"proposta {self.divergence_id} declara confiança alta sem evidência"
            )

    @staticmethod
    def abstencao(
        divergence_id: str,
        tipo: str,
        motivo: str,
        cost: Cost | None = None,
        trace: list[TraceEvent] | None = None,
    ) -> "Proposal":
        """Não saber é resposta válida, e precisa ser barata de produzir.

        `tipo` virou parâmetro: qual é o rótulo de "não sei" é decisão do
        domínio. A conciliação passa `DivergenceType.NAO_IDENTIFICADO`; um
        domínio novo passa o que for o não-sei dele.
        """
        return Proposal(
            divergence_id=divergence_id,
            tipo=tipo,
            explicacao=motivo,
            evidencia=[],
            confianca=Confidence.BAIXA,
            acao_sugerida="investigar_manual",
            cost=cost or Cost.zero(),
            trace=trace or [],
        )


@dataclass(frozen=True)
class InvestigationOutput:
    """Tudo que uma passada do investigador produziu."""

    proposals: list[Proposal]
    cost: Cost
