"""Tirar do pool o que não precisa seguir. O item sai RESOLVIDO, com o motivo.

**Este é o único bloco que resolve sem produzir, e isso é deliberado.**
`agent/tarefa.py` impõe a conjunção da §3.1 — transformar é consumir A *e*
produzir B — e tem teste chamado `test_resolver_sem_produzir_e_erro_alto`. A
razão de lá: uma triagem que decide "isto é spam" e não produz nada faz o item
SUMIR do run, sem ninguém depois e sem sintoma.

Aqui sumir é o pedido, e a diferença entre os dois casos é que este bloco se
chama filtro: quem o arrastou para o board disse que queria descartar. O que
não pode é o descarte ser mudo, e não é — cada item sai com uma `Resolution`
que nomeia o predicado que o descartou, então o trace responde "por que este
item não chegou ao agente?" sem ninguém precisar reconstituir.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.regras.predicado import Comparacao, Predicado


@dataclass(frozen=True)
class Filtro:
    """Item que passa no predicado sai do pool."""

    kind: str
    campo: str
    teste: str
    valor: str = ""
    # O que o trace vai dizer. Default honesto em vez de vazio: uma resolução
    # sem regra nomeada é um item que sumiu sem explicação.
    motivo: str = "descartado por filtro"
    name: str = "filtro"
    resumo: str = "descarta do pool o item que passa no teste"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError(f"{self.name!r}: diga sobre qual kind ele roda")
        object.__setattr__(
            self,
            "_predicado",
            Predicado(campo=self.campo, teste=Comparacao(self.teste), valor=self.valor),
        )

    @property
    def predicado(self) -> Predicado:
        return self._predicado  # type: ignore[attr-defined]

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=self.resumo,
            consome=frozenset({self.kind}),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(
            resolutions=[
                Resolution(
                    item_ids=frozenset({item.id}),
                    produced_by=self.name,
                    rule=f"{self.motivo}: {self.predicado}",
                    evidence={"campo": self.predicado.campo},
                )
                for item in work.of_kind(self.kind)
                if self.predicado.aprova(item.payload)
            ]
        )


__all__ = ["Filtro"]
