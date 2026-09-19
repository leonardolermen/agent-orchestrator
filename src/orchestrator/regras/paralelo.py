"""Todo item vai para TODOS os ramos. É duplicação, não roteamento.

**A diferença que faz este bloco existir.** `condicao` e `tabela` roteiam: cada
item vai para UM ramo, escolhido por um teste ou pelo valor de um campo. Isso
cobre "se o risco for alto, mande para revisão" e não cobre nada do desenho
abaixo, que é o caso mais comum de paralelismo:

        ┌─→ checagem de fraude ─┐
    ─── ┤                       ├─→ junção ───
        └─→ checagem de KYC ────┘

Aqui TODA transação passa pelas duas. Nenhum roteador faz isso, porque roteador
escolhe — e escolher é exatamente o que não se quer.

**Consome e produz, em conjunção, como manda a §3.1.** O original sai do pool e
N cópias entram, uma por ramo. Não consumir deixaria o mesmo dado em dois
lugares: o original seguiria disputando os degraus de baixo junto com as cópias
dele.

O payload atravessa INTACTO e é o MESMO objeto em todas as cópias. Ele é
congelado, então compartilhá-lo é seguro e evita N cópias de um dado que
ninguém vai mudar.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras.ramos import id_no_ramo


@dataclass(frozen=True)
class Paralelo:
    """Um item entra, N cópias saem — uma por ramo."""

    kind: str
    # Os kinds dos ramos. Cada degrau que consome um deles roda sobre a sua
    # cópia, e os ramos não se veem.
    ramos: tuple[str, ...]
    name: str = "paralelo"
    resumo: str = "todo item segue por todos os ramos ao mesmo tempo"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError(f"{self.name!r}: diga qual kind entra neste bloco")
        if len(self.ramos) < 2:
            raise ValueError(
                f"{self.name!r}: {len(self.ramos)} ramo(s). abrir em um ramo só é "
                f"trocar o kind do item e nada mais — para isso existe a "
                f"`condicao`, que ao menos diz sob que condição"
            )
        repetidos = sorted({r for r in self.ramos if self.ramos.count(r) > 1})
        if repetidos:
            raise ValueError(
                f"{self.name!r}: ramo repetido {repetidos}. duas cópias no mesmo "
                f"kind seriam o mesmo item duas vezes no mesmo degrau"
            )
        if self.kind in self.ramos:
            raise ValueError(
                f"{self.name!r}: o ramo {self.kind!r} é o próprio kind de "
                f"entrada. o bloco alimentaria a si mesmo"
            )

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=self.resumo,
            consome=frozenset({self.kind}),
            produz=frozenset(self.ramos),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        resolucoes, produzidos = [], []
        for item in work.of_kind(self.kind):
            resolucoes.append(
                Resolution(
                    item_ids=frozenset({item.id}),
                    produced_by=self.name,
                    rule=f"aberto em {len(self.ramos)} ramos: {', '.join(self.ramos)}",
                    evidence={"ramos": list(self.ramos)},
                )
            )
            produzidos.extend(
                WorkItem(
                    id=id_no_ramo(item.id, ramo),
                    kind=ramo,
                    payload=item.payload,
                    origem=self.name,
                )
                for ramo in self.ramos
            )
        return ResolverOutput(resolutions=resolucoes, produced=tuple(produzidos))


__all__ = ["Paralelo"]
