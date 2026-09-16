"""Procurement: "quem fornece isto?"

O segundo dos três verticais do teste de generalidade (spec de composição §1.3).
Cascata completa: duas regras baratas, um agente, e o humano fechando.

Existe para ser escrito, não para ser usado. O que ele prova é que um domínio
com cardinalidade e vocabulário completamente diferentes da conciliação cabe no
kernel **sem tocar em uma linha dele**.

O que ele exercita e a conciliação não exercita:
  - dois `kind` com relação 1:N no OUTRO sentido (uma requisição, N fornecedores
    candidatos — a conciliação é N lançamentos para M lançamentos);
  - uma `Resolution` que consome DOIS itens de kinds diferentes sem que exista
    nenhuma regra de "um de cada lado" (essa regra é da conciliação, e mora lá);
  - um resolver de classe `HUMANO` que não é o `RevisorHumano` da conciliação.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Confidence, Proposal, Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet

REQUISICAO = "requisicao"
FORNECEDOR = "fornecedor"


@dataclass(frozen=True)
class Requisicao:
    id: str
    item: str
    quantidade: int


@dataclass(frozen=True)
class Fornecedor:
    id: str
    nome: str
    itens: frozenset[str]
    preferido: bool = False


def pool(requisicoes: list[Requisicao], fornecedores: list[Fornecedor]) -> WorkSet:
    """Requisições primeiro, fornecedores depois. Mesma disciplina de ordem que
    `models.pool` — a ordem de `items` é a ordem em que tudo é percorrido."""
    return WorkSet(
        items=tuple(WorkItem(id=r.id, kind=REQUISICAO, payload=r) for r in requisicoes)
        + tuple(WorkItem(id=f.id, kind=FORNECEDOR, payload=f) for f in fornecedores)
    )


def _atende(f: Fornecedor, r: Requisicao) -> bool:
    return r.item in f.itens


@dataclass
class FornecedorPreferido:
    """Regra 1: existe fornecedor preferido que atende? Resolve de graça."""

    name: str = field(default="preferido", init=False)
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "fornecedor preferido")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        fornecedores = [i for i in work.of_kind(FORNECEDOR) if i.payload.preferido]
        usados: set[str] = set()
        saida = []
        for req in work.of_kind(REQUISICAO):
            escolhido = next(
                (
                    f
                    for f in fornecedores
                    if f.id not in usados and _atende(f.payload, req.payload)
                ),
                None,
            )
            if escolhido is None:
                continue
            usados.add(escolhido.id)
            saida.append(
                Resolution(
                    item_ids=frozenset({req.id, escolhido.id}),
                    produced_by=self.name,
                    rule="fornecedor preferido atende o item",
                    evidence={"item": req.payload.item, "fornecedor": escolhido.payload.nome},
                )
            )
        return ResolverOutput(resolutions=saida)


@dataclass
class ComprasAnteriores:
    """Regra 2: qualquer fornecedor que já atenda o item. Também de graça."""

    name: str = field(default="anteriores", init=False)
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "compras anteriores")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        fornecedores = list(work.of_kind(FORNECEDOR))
        usados: set[str] = set()
        saida = []
        for req in work.of_kind(REQUISICAO):
            escolhido = next(
                (
                    f
                    for f in fornecedores
                    if f.id not in usados and _atende(f.payload, req.payload)
                ),
                None,
            )
            if escolhido is None:
                continue
            usados.add(escolhido.id)
            saida.append(
                Resolution(
                    item_ids=frozenset({req.id, escolhido.id}),
                    produced_by=self.name,
                    rule="fornecedor já usado atende o item",
                    evidence={"item": req.payload.item},
                )
            )
        return ResolverOutput(resolutions=saida)


@dataclass
class BuscadorDeFornecedor:
    """Classe AGENTE. Esqueleto: não chama modelo nenhum, e dizer que chama
    seria mentir. O que ele exercita é a FORMA — devolve `proposals`, nunca
    `resolutions`, porque proposta não resolve."""

    name: str = field(default="buscador", init=False)
    cost_class: CostClass = field(default=CostClass.AGENTE, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "busca fornecedor novo")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(
            proposals=[
                Proposal(
                    item_id=r.id,
                    tipo="FORNECEDOR_NOVO",
                    explicacao=f"nenhum fornecedor conhecido atende {r.payload.item!r}",
                    evidencia=[f"requisicao {r.id}"],
                    confianca=Confidence.BAIXA,
                    acao_sugerida="cotar_mercado",
                )
                for r in work.of_kind(REQUISICAO)
            ],
            cost=Cost.zero(),
        )


@dataclass
class CompradorHumano:
    """Classe HUMANO, e NÃO é o `RevisorHumano` da conciliação.

    A existência deste resolver é metade do teste: se "humano" só pudesse ser
    a fila de revisão de conciliação, a classe `HUMANO` seria um detalhe daquele
    domínio em vez de um degrau da cascata.
    """

    aprovacoes: dict[str, str] = field(default_factory=dict)

    name: str = field(default="comprador", init=False)
    cost_class: CostClass = field(default=CostClass.HUMANO, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "decisão do comprador")

    def resolve(self, work: WorkSet) -> ResolverOutput:
        presentes = work.ids()
        return ResolverOutput(
            resolutions=[
                Resolution(
                    item_ids=frozenset({req, forn}),
                    produced_by=self.name,
                    rule="decisão do comprador",
                    evidence={"aprovado_por": "comprador@empresa"},
                )
                for req, forn in self.aprovacoes.items()
                # Decisão obsoleta vira silêncio, não erro — a mesma política
                # que `RevisorHumano` aplica na conciliação.
                if req in presentes and forn in presentes
            ]
        )


def definition(aprovacoes: dict[str, str] | None = None) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="procurement",
        name="Seleção de fornecedor",
        stages=(
            Stage(
                name="quem fornece isto?",
                cascade=(
                    FornecedorPreferido(),
                    ComprasAnteriores(),
                    BuscadorDeFornecedor(),
                    CompradorHumano(aprovacoes=aprovacoes or {}),
                ),
            ),
        ),
    )
