"""O quadro branco: como agentes de uma tripulação se comunicam.

**Comunicação é via `SharedContext`, nunca mensagem livre.** Chat entre agentes
é o modo mais rápido conhecido de queimar orçamento sem produzir nada — N
agentes concordando educadamente por seis turnos, cada turno pago. Com um quadro
branco, **uma contribuição que não muda o estado não custa um turno de ninguém**,
e isso aqui não é slogan: `write` com o mesmo valor devolve o MESMO contexto, e
o Crew para quando o contexto para de mudar.

**Toda escrita é atribuída.** Sem autor, o trace de uma tripulação vira um monte
de texto sem dono, e a pergunta que o produto precisa responder — *qual agente
contribuiu com o quê, e a que custo* — fica sem resposta. É a mesma razão de
`Resolution.produced_by` existir.

**Imutável, como todo o resto do kernel.** `write` devolve um contexto novo. Um
quadro branco mutável passado para N agentes seria estado compartilhado num
sistema cuja propriedade central é execução determinística — o mesmo run com a
mesma entrada tem de dar a mesma coisa, e ordem de mutação é a primeira coisa
que quebra isso.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContextEntry:
    """Uma contribuição, com dono."""

    author: str
    key: str
    value: Any
    round: int = 0

    def render(self) -> str:
        return f"[{self.author}] {self.key}: {self.value}"


@dataclass(frozen=True)
class SharedContext:
    """Quadro branco versionado. Nada é apagado, nada é sobrescrito.

    Append-only pela mesma razão da fila e do armazém de casos: uma
    contribuição substituída mudaria, depois do fato, o que um agente leu
    quando decidiu — e o trace passaria a descrever uma execução que não
    aconteceu.
    """

    entries: tuple[ContextEntry, ...] = field(default_factory=tuple)

    def write(self, author: str, key: str, value: Any, *, round: int = 0) -> "SharedContext":
        """Acrescenta uma contribuição, ou devolve ESTE contexto se nada mudou.

        A checagem de "nada mudou" é o que dá dente à regra do §10.4. Sem ela,
        três agentes repetindo a mesma conclusão produziriam três entradas, o
        contexto pareceria estar evoluindo, e o Crew rodaria `max_rounds`
        inteiras concordando consigo mesmo — com cada rodada custando um turno
        por agente.
        """
        if not author:
            raise ValueError(
                "escrita sem autor: o trace de uma tripulação sem dono não "
                "responde qual agente contribuiu com o quê"
            )
        atual = self.ultimo(key)
        if atual is not None and atual.value == value:
            return self
        return SharedContext(
            entries=(*self.entries, ContextEntry(author, key, value, round))
        )

    def read(self, key: str) -> tuple[ContextEntry, ...]:
        return tuple(e for e in self.entries if e.key == key)

    def ultimo(self, key: str) -> ContextEntry | None:
        entradas = self.read(key)
        return entradas[-1] if entradas else None

    def autores(self) -> tuple[str, ...]:
        vistos: list[str] = []
        for e in self.entries:
            if e.author not in vistos:
                vistos.append(e.author)
        return tuple(vistos)

    def __len__(self) -> int:
        return len(self.entries)

    def render(self) -> str:
        """O que vai para o prompt do próximo agente.

        Ordem de escrita, e não agrupado por chave: o próximo agente precisa
        saber em que ORDEM as conclusões apareceram, porque uma contribuição
        que responde à anterior perde o sentido reordenada.
        """
        if not self.entries:
            return ""
        return "\n".join(e.render() for e in self.entries)
