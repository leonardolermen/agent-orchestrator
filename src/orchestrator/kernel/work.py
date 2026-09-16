"""O trabalho que ainda não foi resolvido.

Este módulo é a razão de o kernel existir. Antes dele, `WorkSet` tinha
`bank: list[BankEntry]` e `ledger: list[LedgerEntry]` nos campos — o contrato
genérico de resolução sabendo o que é um lançamento bancário. Enquanto isso
fosse verdade, nenhum segundo domínio cabia sem tocar no núcleo, e produto e
plataforma eram a mesma coisa.

Aqui o kernel só sabe mover ids. O que É cada item, e o que significa o `kind`
dele, é assunto do domínio — e nenhum código deste arquivo consegue perguntar.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # kernel -> kernel é permitido; o import fica sob TYPE_CHECKING só para
    # deixar explícito que `work.py` não PRECISA de `resolution.py` em tempo de
    # execução — ele só move ids, e `item_ids` é tudo que ele consulta.
    from orchestrator.kernel.resolution import Resolution


@dataclass(frozen=True)
class WorkItem:
    """Uma unidade de trabalho ainda não resolvida.

    `payload` é um dataclass congelado do domínio — `BankEntry` hoje, um item
    de compra ou uma issue amanhã. O kernel NUNCA o inspeciona: ele só move
    ids. É isso que mantém as garantias do domínio (dinheiro em int, campos
    congelados) sem que o kernel precise conhecê-las.

    `kind` existe porque um pool pode ser heterogêneo: a conciliação tem dois
    lados assimétricos no mesmo `WorkSet`. Um domínio de um lado só — o caso
    degenerado de `domains/swe` — usa um `kind` e ignora o campo.

    Por que `kind: str` e não `WorkSet[T]` genérico: `T` teria de ser
    `BankEntry | LedgerEntry`, e todo resolver receberia uma união para
    estreitar. `kind` modela a assimetria direto, e o estreitamento acontece
    uma vez, nos acessores do domínio.
    """

    id: str
    kind: str
    payload: Any

    def __post_init__(self) -> None:
        # Id vazio não identifica nada, e um pool com dois itens de id "" faria
        # `without()` remover os dois ao resolver um. Falha alto na construção,
        # como toda config inválida neste repositório.
        if not self.id:
            raise ValueError("WorkItem exige um id não vazio")
        if not self.kind:
            raise ValueError(f"WorkItem {self.id!r} exige um kind não vazio")


@dataclass(frozen=True)
class WorkSet:
    """O pool do que ainda não foi resolvido, numa passagem da cascata.

    `items` é tupla, não lista: `WorkSet` é imutável de verdade, e não
    imutável na casca como `Dataset` (cujo docstring registra que `frozen=True`
    não torna as listas imutáveis). Um resolver que recebesse uma lista poderia
    mutá-la e mudar o pool por baixo do motor.

    A ORDEM é preservada em toda operação. Não é detalhe estético: o golden de
    12 sementes depende da ordem em que as divergências saem, e ela vem daqui.
    """

    items: tuple[WorkItem, ...] = ()

    def __post_init__(self) -> None:
        # Id repetido é a falha que `without()` não consegue expressar: remover
        # um id removeria os dois, e o pool encolheria mais do que a resolução
        # pediu. Barato de checar aqui, impossível de diagnosticar depois.
        vistos = set()
        for item in self.items:
            if item.id in vistos:
                raise ValueError(f"id repetido no WorkSet: {item.id!r}")
            vistos.add(item.id)

    def of_kind(self, kind: str) -> tuple[WorkItem, ...]:
        """Os itens de um tipo, na ordem em que entraram."""
        return tuple(i for i in self.items if i.kind == kind)

    def payloads(self, kind: str) -> tuple[Any, ...]:
        """Os payloads de um tipo. Atalho do acessor tipado do domínio."""
        return tuple(i.payload for i in self.items if i.kind == kind)

    def ids(self) -> frozenset[str]:
        return frozenset(i.id for i in self.items)

    def without(self, resolutions: Iterable["Resolution"]) -> "WorkSet":
        """O pool sem o que estas resoluções consumiram.

        Recebe resoluções, NUNCA um `ResolverOutput`, e é deliberado: assim não
        existe assinatura pela qual uma PROPOSTA possa chegar aqui. A
        invariante "proposta não resolve" deixa de ser regra que alguém lembra
        e passa a ser coisa que o tipo não sabe expressar.

        Preservado verbatim do `workset.py` original, que trazia esta mesma
        nota. A única mudança é o tipo do argumento: `list[MatchResult]` virou
        `Iterable[Resolution]` — mesma garantia, sem conhecer conciliação.
        """
        consumidos: set[str] = set()
        for r in resolutions:
            consumidos |= r.item_ids
        if not consumidos:
            return self
        return WorkSet(items=tuple(i for i in self.items if i.id not in consumidos))
