"""A fonte como DEGRAU: um bloco que lê de fora e põe o trabalho no pool.

Até aqui a fonte era escolhida na hora de rodar, e o workflow não sabia de onde
vinha o dado. Isso funciona enquanto alguém aperta "rodar" — e não funciona para
um `Trigger`, porque um run disparado por webhook não tem ninguém para escolher
a fonte. Este bloco é o que torna um workflow autossuficiente.

**Por que ele consome `inicio` em vez de não consumir nada.** A tentação era
`consome=frozenset()`, já que ele não tira nada do pool. Custaria caro e em
silêncio: o default vazio significa "vejo o pool INTEIRO", e a guarda de beco sem
saída do kernel desliga no grafo todo assim que um único stage usa esse default
(`if any(not s.consome for s in self.stages): return`, com o porquê escrito
lá). Acrescentar um bloco de entrada apagaria a checagem de kind órfão do
workflow inteiro, e ninguém veria.

Então o run começa com UM item semente de kind `inicio`, e este bloco o consome
para produzir o trabalho de verdade. Três coisas caem no lugar de uma vez: o
pool não começa vazio (a borda recusa pool vazio, e com razão — "sem item não há
execução"), `consome` é verdade, e a guarda continua viva.

**A leitura acontece no `resolve`, não na construção.** Compor não pode tocar em
banco nem em rede: `construir_composicao` roda em `/api/composicoes`, que é a
rota que valida sem executar. Uma fonte lida na construção faria "validar" abrir
conexão.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.source import Source
from orchestrator.kernel.work import WorkSet

# O kind do item SEMENTE. Um só, e o `/runs` o põe no pool quando o workflow
# declara consumi-lo — é assim que a borda sabe que este workflow carrega a
# própria entrada e não espera uma fonte no pedido.
INICIO = "inicio"


@dataclass(frozen=True)
class Entrada:
    """Lê a fonte e produz o trabalho. O `Input` do canvas."""

    fonte: Source
    # Os kinds que esta fonte entrega. DECLARADO, como todo `produz`: o grafo
    # precisa ser conhecido antes de rodar, e um kind que só aparece quando o
    # dado chega é um beco sem saída descoberto em produção.
    produz: tuple[str, ...]
    name: str = "entrada"
    resumo: str = "lê a fonte e põe o trabalho no pool"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        if not self.produz:
            raise ValueError(
                f"{self.name!r}: diga que kind esta fonte entrega. sem isso o "
                f"degrau seguinte não tem como declarar que o consome, e o "
                f"motor recusa kind produzido e não declarado"
            )
        if INICIO in self.produz:
            raise ValueError(
                f"{self.name!r}: produz {INICIO!r}, que é o próprio kind da "
                f"semente. o bloco alimentaria a si mesmo"
            )

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=self.resumo,
            consome=frozenset({INICIO}),
            produz=frozenset(self.produz),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        sementes = list(work.of_kind(INICIO))
        if not sementes:
            # Sem semente não lê: o degrau já roda uma vez por ronda, e uma
            # leitura por ronda duplicaria o trabalho inteiro na segunda.
            return ResolverOutput()
        carregado = self.fonte.load()
        # `ref` UMA vez, numa variável. Em `HttpSource` ele é um hash do
        # conteúdo, e calculá-lo BUSCA: escrever `self.fonte.ref` duas vezes
        # aqui somava duas requisições às que `load()` já fez — três idas à API
        # do parceiro para uma leitura, e nada no tipo avisa disso.
        ref = self.fonte.ref
        return ResolverOutput(
            # Consome a semente E produz o trabalho — a conjunção da §3.1. Não
            # consumir faria a semente sobrar no pool para sempre, aparecendo na
            # lacuna como um item que ninguém deu conta.
            resolutions=[
                Resolution(
                    item_ids=frozenset(s.id for s in sementes),
                    produced_by=self.name,
                    rule=f"carregado de {ref}",
                    evidence={"itens": len(carregado.items), "ref": ref},
                )
            ],
            produced=tuple(carregado.items),
        )


__all__ = ["INICIO", "Entrada"]
