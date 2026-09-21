"""Um item de um lado cobrindo N do outro. Pagamento agregado, entrega parcial.

É a forma do L3 da conciliação sem os campos cravados: agrupa a direita por uma
chave, e procura o subconjunto cuja soma bate com o valor da esquerda, dentro de
uma folga.

**Os dois tetos não são otimização, são o que impede dois defeitos.** A busca é
combinatória — `O(C^max_itens)` no número de candidatos —, então sem
`max_candidatos` alguns poucos milhares de itens travam o run. E pool maior é
mais oportunidade de uma soma coincidir por acaso, então o teto também segura
falso positivo. Estourou, o item simplesmente não é agrupado e segue para o
próximo degrau — que é o destino previsto de tudo que uma regra barata não
resolve.

**O que este bloco NÃO herda do L3**, e vale dizer com nome: a guarda
`if be.amount >= 0: continue`, que traduz "crédito é recebimento e não sai
procurando fatura a pagar". Isso não é configuração de campo, é conhecimento
sobre o negócio — e é o mesmo motivo pelo qual o L3 continua no domínio. Quem
quiser o efeito aqui compõe um `filtro` antes.
"""

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.regras.campos import valor_do_campo
from orchestrator.regras.pares import Par, interpretar, interpretar_todos


@dataclass(frozen=True)
class Agrupamento:
    """Um item da esquerda casa com N da direita cuja soma bate."""

    esquerda: str
    direita: str
    # Por qual campo os candidatos se agrupam. Sem chave, qualquer combinação do
    # pool inteiro seria candidata e a soma sozinha casaria itens sem relação.
    chave: tuple[str, ...]
    # `"amount=net_amount"`: o campo que precisa SOMAR.
    soma: str
    max_itens: int = 4
    max_diferenca: int = 0
    modulo: bool = False
    max_candidatos: int = 24
    name: str = "agrupamento"
    resumo: str = "um item de um lado cobrindo N do outro, pela soma"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_chave", interpretar_todos(self.chave))
        object.__setattr__(self, "_soma", interpretar(self.soma))
        # Tamanho menor que 2 esvazia o range de combinações, e o bloco nunca
        # agruparia nada — sem erro e sem aviso.
        if self.max_itens < 2:
            raise ValueError(
                f"{self.name!r}: agrupar exige pelo menos 2 itens: {self.max_itens}"
            )
        if self.max_diferenca < 0:
            raise ValueError(
                f"{self.name!r}: max_diferenca não pode ser negativo: "
                f"{self.max_diferenca}"
            )
        if self.max_candidatos < self.max_itens:
            raise ValueError(
                f"{self.name!r}: teto de candidatos ({self.max_candidatos}) não "
                f"pode ser menor que o tamanho máximo do grupo ({self.max_itens})"
            )
        if self.esquerda == self.direita:
            raise ValueError(
                f"{self.name!r}: os dois lados são o kind {self.esquerda!r}. um "
                f"item casaria consigo mesmo"
            )

    @property
    def _pares_chave(self) -> tuple[Par, ...]:
        return self._chave  # type: ignore[attr-defined]

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=self.resumo,
            consome=frozenset({self.esquerda, self.direita}),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(resolutions=self._casar(work))

    def _chave_de(self, payload: Any, lado: str) -> tuple[Any, ...] | None:
        valores = []
        for par in self._pares_chave:
            v = valor_do_campo(payload, par.esquerda if lado == "esq" else par.direita)
            if v is None:
                return None
            valores.append(v)
        return tuple(valores)

    def _valor(self, payload: Any, lado: str) -> float | None:
        par: Par = self._soma  # type: ignore[attr-defined]
        v = valor_do_campo(payload, par.esquerda if lado == "esq" else par.direita)
        if v is None:
            return None
        n = float(v)
        return abs(n) if self.modulo else n

    def _casar(self, work: WorkSet) -> list[Resolution]:
        indice: dict[tuple[Any, ...], list[WorkItem]] = {}
        for item in work.of_kind(self.direita):
            chave = self._chave_de(item.payload, "dir")
            if chave is not None and self._valor(item.payload, "dir") is not None:
                indice.setdefault(chave, []).append(item)

        resultados: list[Resolution] = []
        usados: set[str] = set()
        for item in work.of_kind(self.esquerda):
            chave = self._chave_de(item.payload, "esq")
            alvo = None if chave is None else self._valor(item.payload, "esq")
            if alvo is None:
                continue
            candidatos = [c for c in indice.get(chave, []) if c.id not in usados]
            if len(candidatos) < 2 or len(candidatos) > self.max_candidatos:
                continue
            grupo = self._encontrar(candidatos, alvo)
            if grupo is None:
                continue
            usados.update(c.id for c in grupo)
            resultados.append(
                Resolution(
                    item_ids=frozenset({item.id, *(c.id for c in grupo)}),
                    produced_by=self.name,
                    rule=(
                        f"agrupamento: {len(grupo)} itens somando {alvo:g} "
                        f"(folga {self.max_diferenca})"
                    ),
                    evidence={"itens": len(grupo), "soma": alvo},
                )
            )
        return resultados

    def _encontrar(self, candidatos: list[WorkItem], alvo: float) -> tuple | None:
        """O MENOR grupo que soma o alvo. `None` se nenhum.

        Do menor para o maior de propósito: entre dois grupos que somam igual, o
        de dois itens é mais provavelmente o agrupamento real do que o de
        quatro, que tem mais chance de ser coincidência aritmética.
        """
        for tamanho in range(2, min(self.max_itens, len(candidatos)) + 1):
            for grupo in combinations(candidatos, tamanho):
                total = sum(self._valor(c.payload, "dir") or 0.0 for c in grupo)
                if abs(total - alvo) <= self.max_diferenca:
                    return grupo
        return None


__all__ = ["Agrupamento"]
