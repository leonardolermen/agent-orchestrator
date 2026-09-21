"""Os ramos de um mesmo item se reencontram. O `Merge` do canvas.

Depois de um `paralelo`, o pedido `p1` virou `p1+fraude` e `p1+kyc`, e cada
degrau tratou o seu. Este bloco os reúne: consome os dois e produz um item só,
de volta num kind que o degrau seguinte consome.

**Ele espera TODOS os ramos.** Se um deles ainda não chegou — porque o degrau
daquele ramo não rodou, ou porque o item de lá foi resolvido e saiu do pool —,
nada é consumido e nada é produzido. O que sobra fica no pool e aparece na
LACUNA, contado.

É deliberado, e é a escolha mais conservadora possível: juntar pela metade
produziria um item que parece completo e não é, e o degrau de baixo trabalharia
sobre uma junção que perdeu um lado sem dizer. "Faltou um ramo" é uma lacuna
legítima; um resultado incompleto disfarçado de completo, não.

**Qual payload sobrevive.** O do PRIMEIRO ramo da lista, e a ordem é de quem
configurou. Hoje os ramos de um `paralelo` compartilham o mesmo objeto de
payload, então a escolha não muda nada; ela passa a importar no dia em que algum
bloco transformar o dado de um ramo, e nesse dia é melhor que a regra esteja
escrita do que descoberta.
"""

from dataclasses import dataclass, field
from typing import Any

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras.ramos import id_no_ramo, origem_do_ramo


@dataclass(frozen=True)
class Juncao:
    """N ramos do mesmo item entram, um item sai."""

    ramos: tuple[str, ...]
    produz: str
    name: str = "juncao"
    resumo: str = "reúne os ramos de um mesmo item num só"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        if len(self.ramos) < 2:
            raise ValueError(
                f"{self.name!r}: {len(self.ramos)} ramo(s). juntar um ramo só é "
                f"trocar o kind do item, e não é junção"
            )
        if not self.produz.strip():
            raise ValueError(
                f"{self.name!r}: `produz` vazio. sem o kind de saída, o bloco "
                f"consumiria os ramos sem entregar nada — os itens sumiriam"
            )
        if self.produz in self.ramos:
            raise ValueError(
                f"{self.name!r}: produz {self.produz!r}, que é um dos ramos que "
                f"consome. o bloco alimentaria a si mesmo"
            )

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=self.resumo,
            consome=frozenset(self.ramos),
            produz=frozenset({self.produz}),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        # Por ORIGEM: `p1+fraude` e `p1+kyc` vieram do mesmo `p1`. É a única
        # coisa que diz que os dois são o mesmo pedido, e o contrato dela mora
        # em `ramos.py`.
        por_origem: dict[str, dict[str, WorkItem]] = {}
        for ramo in self.ramos:
            for item in work.of_kind(ramo):
                por_origem.setdefault(origem_do_ramo(item.id), {})[ramo] = item

        resolucoes, produzidos = [], []
        for origem, achados in por_origem.items():
            if len(achados) != len(self.ramos):
                # Falta ramo: não junta. O que sobra fica no pool e aparece na
                # lacuna, contado — melhor que uma junção que perdeu um lado.
                continue
            partes = [achados[r] for r in self.ramos]
            resolucoes.append(
                Resolution(
                    item_ids=frozenset(p.id for p in partes),
                    produced_by=self.name,
                    rule=f"reunidos {len(partes)} ramos de {origem!r}",
                    evidence={"origem": origem, "ramos": list(self.ramos)},
                )
            )
            produzidos.append(
                WorkItem(
                    id=id_no_ramo(origem, self.produz),
                    kind=self.produz,
                    # O payload do PRIMEIRO ramo. Ver o docstring do módulo.
                    payload=_payload(partes),
                    origem=self.name,
                )
            )
        return ResolverOutput(resolutions=resolucoes, produced=tuple(produzidos))


def _payload(partes: list[WorkItem]) -> Any:
    return partes[0].payload


__all__ = ["Juncao"]
