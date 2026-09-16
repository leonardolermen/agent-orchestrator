"""O que um resolver produziu: uma resolução, que RESOLVE.

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
from typing import Any


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
