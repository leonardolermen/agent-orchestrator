"""O caso de avaliação: a entrada, o esperado, e de onde a verdade veio.

**Por que isto é o ativo.** O §1.1 do spec chama o conjunto de avaliação de "a
coisa que um concorrente não copia": prompts, modelos e cascatas são replicáveis
numa tarde; um conjunto de casos com verdade estabelecida, colhido da operação
real, não é. Por isso `avaliacoes/casos/` vai para o git no scaffold enquanto
`data/` não vai.

**A correção que este módulo carrega.** Até aqui a única verdade do projeto era
o gabarito sintético, endereçado por `dataset_id(seed, n, taxa_divergencia)`.
Isso amarra o caso à semente que o gerou: mude o gerador e o caso deixa de
existir. `EvaluationCase.input_snapshot` carrega os PAYLOADS dos itens, não uma
referência — um caso colhido da produção precisa sobreviver ao arquivo que o
originou. Um caso que só existe enquanto a semente existir não é um ativo.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from orchestrator.kernel.work import WorkItem


class Provenance(StrEnum):
    """De onde veio a verdade deste caso.

    A procedência não é metadado decorativo: ela decide o peso. Um caso
    `SINTETICO` tem gabarito perfeito e domínio estreito; um `HUMANO` tem a
    ambiguidade real e o erro de quem revisou. Misturar os dois sem saber qual
    é qual produz um número que não significa nada.
    """

    SINTETICO = "sintetico"
    HUMANO = "humano"
    ESPECIALISTA = "especialista"


@dataclass(frozen=True)
class ExpectedOutcome:
    """O que deveria ter acontecido com um item.

    `kind=None` é "não sei", e é um estado legítimo — um revisor que rejeitou
    uma hipótese afirmou que ELA está errada, não qual é a certa. Forçar um
    tipo aqui inventaria verdade que ninguém estabeleceu, que é precisamente o
    defeito que a avaliação existe para não cometer.
    """

    kind: str | None = None
    should_resolve_deterministically: bool = False
    resolves_with: frozenset[str] = frozenset()
    note: str = ""


@dataclass(frozen=True)
class EvaluationCase:
    """Um caso. Congelado, serializável, independente do que o gerou."""

    id: str
    input_snapshot: tuple[WorkItem, ...]
    expected: ExpectedOutcome
    provenance: Provenance
    created_at: datetime
    source_run_id: str | None = None
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        # Mesma exigência de `Run.started_at` e `Decision.quando`, e pelo mesmo
        # motivo — aqui com uma consequência a mais: `created_at` é o que
        # separa caso de treino de caso de teste na guarda de contaminação
        # (§14.3). Ingênuo, a comparação com `run.started_at` levantaria, e a
        # guarda falharia ABERTA se alguém a envolvesse num try.
        if self.created_at.tzinfo is None:
            raise ValueError(
                f"caso {self.id!r}: `created_at` precisa de fuso (use UTC). "
                f"ele é o que impede o benchmark de medir memorização"
            )
        if not self.input_snapshot:
            raise ValueError(
                f"caso {self.id!r}: sem `input_snapshot` não há o que rodar. "
                f"um caso que não carrega a entrada é uma anotação, não um caso"
            )

    @property
    def item_ids(self) -> frozenset[str]:
        return frozenset(i.id for i in self.input_snapshot)


@dataclass(frozen=True)
class EvalDataset:
    """Um conjunto de casos, com versão derivada do conteúdo.

    `version` é derivada, nunca escrita à mão — mesma disciplina de
    `WorkflowDefinition.version`. Um `BenchmarkResult` guarda a versão do
    dataset que mediu; sem derivação, dois resultados poderiam alegar a mesma
    versão sobre conjuntos diferentes, e a comparação entre eles seria ficção.
    """

    id: str
    cases: tuple[EvaluationCase, ...] = ()
    version: str = field(init=False)

    def __post_init__(self) -> None:
        vistos: set[str] = set()
        for c in self.cases:
            if c.id in vistos:
                raise ValueError(
                    f"caso repetido no dataset {self.id!r}: {c.id!r}. dois "
                    f"casos com o mesmo id fariam a métrica depender da ordem"
                )
            vistos.add(c.id)
        # Ordenado: a versão é do CONJUNTO, não da ordem em que alguém o
        # montou. Sem `sorted`, reordenar a mesma lista produziria outra
        # versão e um falso "o dataset mudou".
        digest = hashlib.sha256(
            "\n".join(sorted(c.id for c in self.cases)).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "version", digest[:12])

    def __len__(self) -> int:
        return len(self.cases)

    def by_item_id(self) -> dict[str, EvaluationCase]:
        """Do id do item para o caso que o contém.

        `WorkSet.__post_init__` já recusa ids repetidos DENTRO de um pool; aqui
        a garantia é entre casos, e é o que permite pontuar um `Run` item a
        item sem ambiguidade.
        """
        indice: dict[str, EvaluationCase] = {}
        for caso in self.cases:
            for item in caso.input_snapshot:
                if item.id in indice:
                    raise ValueError(
                        f"item {item.id!r} aparece em {indice[item.id].id!r} e "
                        f"em {caso.id!r}; a pontuação ficaria ambígua"
                    )
                indice[item.id] = caso
        return indice

    def elegiveis_para(self, started_at: datetime) -> "EvalDataset":
        """Só os casos criados ANTES de um run — a guarda de contaminação.

        Um caso colhido de um run é usado para avaliar runs FUTUROS, nunca o
        que o originou. Sem isto o benchmark mediria memorização: o agente
        seria pontuado contra a correção do próprio erro que acabou de cometer,
        e o número subiria sozinho a cada colheita.

        Devolve um dataset novo, com versão própria — o recorte É um conjunto
        diferente, e dizer que é o mesmo esconderia a exclusão.
        """
        return EvalDataset(
            id=f"{self.id}@antes-de-{started_at.isoformat()}",
            cases=tuple(c for c in self.cases if c.created_at < started_at),
        )
