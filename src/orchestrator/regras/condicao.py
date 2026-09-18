"""Rotear: quem passa no teste vira um item de outro `kind` e segue por outro caminho.

**Este é o `Condition` do canvas, e ele não é uma aresta com um IF.** No motor, o
dado é que escolhe o caminho: um degrau declara `consome={"suspeito"}` e
simplesmente NÃO RODA quando não há item desse kind — "ramo sem trabalho: o
degrau não roda, e isso é a condicional", diz o `runtime/engine.py`. Então
ramificar é produzir o kind que ativa o ramo.

**Consome E produz, em conjunção, e isso não é escolha deste módulo.** É a §3.1,
que `agent/tarefa.py` já impõe com um teste chamado
`test_resolver_sem_produzir_e_erro_alto`: transformar é consumir A *e* produzir
B. Produzir sem consumir deixaria o original no pool, ele apareceria na lacuna
como "ninguém deu conta", e o mesmo dado estaria em dois lugares. Consumir sem
produzir faria o item sumir — que é o `filtro.py`, e ali é o pedido.

O payload atravessa INTACTO. Rotear é mudar de caminho, não mudar o dado; quem
enriquece é a `tabela.py`. Um bloco que fizesse os dois esconderia qual dos dois
aconteceu quando o resultado surpreendesse.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras.predicado import Comparacao, Predicado


@dataclass(frozen=True)
class Condicao:
    """Item que passa no predicado sai como `kind` e volta como `produz`."""

    kind: str
    campo: str
    teste: str
    valor: str = ""
    # O kind do ramo. Precisa estar em `Stage.produz`, senão o motor recusa
    # nomeando o resolver — a guarda existe porque o grafo tem de ser conhecido
    # ANTES de rodar, para o canvas desenhar a seta e a recusa de beco sem saída
    # funcionar.
    produz: str = ""
    name: str = "condicao"
    resumo: str = "quem passa no teste segue por outro ramo"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError(f"{self.name!r}: diga sobre qual kind ele roda")
        if not self.produz.strip():
            raise ValueError(
                f"{self.name!r}: `produz` vazio. sem o kind do ramo, este bloco "
                f"consumiria o item sem entregá-lo a ninguém — o item sumiria do "
                f"run, e para descartar de propósito existe o `filtro`"
            )
        if self.produz == self.kind:
            raise ValueError(
                f"{self.name!r}: produz o mesmo kind que consome ({self.kind!r}). "
                f"o ramo alimentaria a si mesmo"
            )
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
            # Sem esta declaração a composição passaria e a EXECUÇÃO recusaria,
            # com "produziu kind não declarado" — um erro sobre uma escolha que
            # a tela aceitou. `produz_de()` lê daqui.
            produz=frozenset({self.produz}),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        resolucoes, produzidos = [], []
        for item in work.of_kind(self.kind):
            if not self.predicado.aprova(item.payload):
                continue
            resolucoes.append(
                Resolution(
                    item_ids=frozenset({item.id}),
                    produced_by=self.name,
                    rule=f"roteado para {self.produz!r}: {self.predicado}",
                    evidence={"ramo": self.produz},
                )
            )
            produzidos.append(
                WorkItem(
                    # `+ramo` no id, como `agent/tarefa.py` faz com `+r`: o item
                    # produzido é OUTRO item, e um id igual ao do consumido faria
                    # `WorkSet` recusar por repetição — o que é a guarda certa
                    # falhando pelo motivo errado.
                    id=f"{item.id}+{self.produz}",
                    kind=self.produz,
                    payload=item.payload,
                    origem=self.name,
                )
            )
        return ResolverOutput(resolutions=resolucoes, produced=tuple(produzidos))


__all__ = ["Condicao"]
