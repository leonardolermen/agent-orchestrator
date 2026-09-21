"""De-para: o VALOR de um campo escolhe para qual ramo o item vai.

`("PJ=empresa", "PF=pessoa")` quer dizer: item cujo campo vale `PJ` sai como
kind `empresa`, cujo campo vale `PF` sai como `pessoa`. É a `condicao` com
muitos ramos em vez de um — o `Switch` do canvas.

**Por que ela ROTEIA e não ENRIQUECE.** "De-para" também poderia significar "o
item ganha um campo valendo `empresa`", que é a leitura de `Transform`. Neste
motor isso sai caro e em silêncio: `WorkItem.payload` costuma ser uma dataclass
CONGELADA do domínio, então acrescentar campo obriga a produzir um `dict` no
lugar — e todo bloco tipado depois dele para de funcionar sobre aquele item, sem
erro, porque `ResolverDescription.payloads` é conferido contra a FONTE e não
contra o que um resolver do meio da cascata produziu.

Rotear não tem esse problema: o payload atravessa intacto e quem muda é o kind,
que é justamente a coisa que o grafo já sabe conferir antes de rodar.

**Item cujo valor não está na tabela não é tocado.** Ele fica no pool para o
próximo degrau. A alternativa — um ramo "resto" implícito — esconderia a
diferença entre "classifiquei como resto" e "não soube classificar", e essa
diferença é a que mais custa caro neste produto.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras.campos import valor_do_campo
from orchestrator.regras.pares import interpretar_todos
from orchestrator.regras.ramos import id_no_ramo


@dataclass(frozen=True)
class Tabela:
    """O valor do campo escolhe o kind de saída."""

    kind: str
    campo: str
    # `("PJ=empresa", "PF=pessoa")`. Reusa a forma `de=para` dos outros blocos,
    # e por isso cabe no editor de lista que a tela já tem.
    de_para: tuple[str, ...]
    name: str = "tabela"
    resumo: str = "o valor do campo escolhe o ramo"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError(f"{self.name!r}: diga sobre qual kind ele roda")
        if not self.campo.strip():
            raise ValueError(f"{self.name!r}: diga qual campo decide o ramo")
        pares = interpretar_todos(self.de_para)
        rotas = {p.esquerda: p.direita for p in pares}
        # Um ramo que devolve o mesmo kind alimentaria a si mesmo.
        proprios = sorted(d for d in rotas.values() if d == self.kind)
        if proprios:
            raise ValueError(
                f"{self.name!r}: a rota {proprios} devolve o mesmo kind que "
                f"entra ({self.kind!r}). o ramo alimentaria a si mesmo"
            )
        object.__setattr__(self, "_rotas", rotas)

    @property
    def rotas(self) -> dict[str, str]:
        return self._rotas  # type: ignore[attr-defined]

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=self.resumo,
            consome=frozenset({self.kind}),
            # TODOS os destinos, não só os que algum item vai usar: o grafo
            # precisa ser conhecido antes de rodar, e um destino que só aparece
            # quando o dado certo chega é um beco sem saída descoberto em
            # produção.
            produz=frozenset(self.rotas.values()),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        resolucoes, produzidos = [], []
        for item in work.of_kind(self.kind):
            valor = valor_do_campo(item.payload, self.campo)
            destino = self.rotas.get(str(valor)) if valor is not None else None
            if destino is None:
                continue
            resolucoes.append(
                Resolution(
                    item_ids=frozenset({item.id}),
                    produced_by=self.name,
                    rule=f"{self.campo}={valor} → {destino}",
                    evidence={"ramo": destino, self.campo: valor},
                )
            )
            produzidos.append(
                WorkItem(
                    id=id_no_ramo(item.id, destino),
                    kind=destino,
                    payload=item.payload,
                    origem=self.name,
                )
            )
        return ResolverOutput(resolutions=resolucoes, produced=tuple(produzidos))


__all__ = ["Tabela"]
