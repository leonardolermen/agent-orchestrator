"""O contrato único: regra, agente e humano com a mesma forma.

Antes deste módulo havia dois conceitos — `Matcher`, que casa, e
`Investigator`, que investiga — e por isso `reconcile` tinha dois parâmetros e
não havia cascata nenhuma no código. Ver o §1 do spec desta fatia.
"""

from dataclasses import dataclass, field
from typing import Protocol

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.resolution import Proposal, Resolution
from orchestrator.kernel.work import WorkItem, WorkSet


@dataclass(frozen=True)
class ResolverOutput:
    """O que um resolver produziu.

    `resolutions` e `proposals` são campos separados, e é deliberado: uma
    resolução RESOLVE — sai do pool —, uma proposta apenas explica e o item
    continua em aberto até um humano aprovar. Unificar os dois num tipo só com
    um campo de status transformaria uma garantia de tipo numa convenção
    verificada, e um filtro esquecido viraria resolução fantasma.

    O campo chamava-se `matches` — palavra de conciliação. `resolutions` diz a
    mesma coisa sem supor que resolver seja casar.
    """

    resolutions: list[Resolution] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    # O que este resolver CRIOU. Campo separado de `resolutions` pela mesma
    # razão que `proposals` é separado: resolução consome, produção cria, e um
    # tipo único com campo de status transformaria duas garantias de tipo numa
    # convenção que alguém precisa verificar.
    #
    # `proposals` não aparece em nenhuma das duas expressões do motor
    # (`without` e `com`), e é essa ausência — agora que há DUAS maneiras de o
    # pool mudar — que mantém "proposta não resolve" estrutural.
    produced: tuple[WorkItem, ...] = ()
    cost: Cost = field(default_factory=Cost.zero)


@dataclass(frozen=True)
class ResolverDescription:
    """O que a API publica sobre um resolver. Dado, não comportamento."""

    name: str
    cost_class: CostClass
    summary: str
    # O que este resolver EXIGE do `WorkItem.payload`, por `kind`. Vazio — o
    # default — significa "não inspeciono o payload": um resolver que só move
    # ids, ou que trata o payload como mapa de campos, roda sobre qualquer
    # fonte.
    #
    # **Existe porque `payload: Any` é uma promessa que o kernel não pode
    # cumprir sozinho.** `ExactMatcher` lê `be.document`; `ArquivoSource`
    # entrega `dict`. Sem declaração, essa combinação atravessa a borda inteira
    # e estoura como `AttributeError: 'dict' object has no attribute
    # 'document'` a três camadas de distância de quem a escolheu — um erro de
    # servidor sobre uma escolha do cliente.
    #
    # DECLARADO e não inferido, pela mesma razão que `Stage.produz`: quem
    # compõe precisa da recusa ANTES de executar, e uma propriedade que só
    # existe depois de rodar não previne nada. E declarado no RESOLVER e não
    # numa lista de nomes na borda, porque uma lista apodrece no dia em que
    # alguém escreve o próximo resolver tipado.
    #
    # O kernel não usa este campo para nada — ele continua sem inspecionar
    # payload. Quem lê é a borda que junta uma FONTE a um WORKFLOW, e hoje há
    # uma só: `api/app.py`.
    payloads: dict[str, type] = field(default_factory=dict)


class Resolver(Protocol):
    """Uma tentativa de resolução dentro de uma cascata."""

    name: str
    cost_class: CostClass

    def resolve(self, work: WorkSet) -> ResolverOutput: ...

    def describe(self) -> ResolverDescription: ...
