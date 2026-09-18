"""Casar dois lados por campos que coincidem exatamente. Sem saber de que domínio.

É a forma que `ExactMatcher` (o L1 da conciliação) tinha por dentro, com os
nomes de campo saindo de quem configura em vez de estarem escritos no código:
indexa um lado pela chave, varre o outro, e o primeiro candidato livre ganha.

**`modulo` existe por uma razão concreta, e ela não é de conciliação.** Quando
dois sistemas registram a mesma transação com sinais opostos — uma saída é
negativa de um lado e positiva do outro —, os valores são iguais em magnitude e
diferentes em sinal. `ExactMatcher` resolvia isso com um `abs()` escrito no
meio da chave, o que também era a razão de ele não poder ser genérico. Aqui o
`abs()` vira escolha de quem configura, campo a campo.
"""

from dataclasses import dataclass, field
from typing import Any

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.regras.campos import valor_do_campo
from orchestrator.regras.pares import Par, interpretar_todos


@dataclass(frozen=True)
class Igualdade:
    """Um item da esquerda casa com um da direita quando todos os campos batem."""

    # Os dois `WorkItem.kind`. Não são "banco" e "contábil" por default: um
    # default aqui seria conciliação vazando para dentro de uma regra que existe
    # justamente para não ter domínio.
    esquerda: str
    direita: str
    # `("document", "amount=net_amount", "date=cash_date")`. Ver `pares.py`.
    campos: tuple[str, ...]
    # Campos (pelo nome do lado ESQUERDO) comparados por `abs()` nos dois lados.
    modulo: tuple[str, ...] = ()
    name: str = "igualdade"
    resumo: str = "os campos escolhidos coincidem exatamente"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        # Validar é construir, como no `ToolRegistry`: o que passa daqui casa.
        # Uma regra malformada que só falhasse ao rodar apareceria como "não
        # casou nada" — indistinguível de "não havia o que casar".
        pares = interpretar_todos(self.campos)
        object.__setattr__(self, "_pares", pares)
        nomes = {p.esquerda for p in pares}
        desconhecidos = sorted(set(self.modulo) - nomes)
        if desconhecidos:
            raise ValueError(
                f"{self.name!r}: `modulo` cita {desconhecidos}, que não está "
                f"entre os campos comparados ({sorted(nomes)}). o nome vai pelo "
                f"lado ESQUERDO do par"
            )
        if self.esquerda == self.direita:
            raise ValueError(
                f"{self.name!r}: os dois lados são o kind {self.esquerda!r}. um "
                f"item casaria consigo mesmo"
            )

    @property
    def pares(self) -> tuple[Par, ...]:
        return self._pares  # type: ignore[attr-defined]

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary=self.resumo,
            # `payloads` VAZIO: esta regra não exige tipo nenhum, ela lê campos.
            # É o caso que o default do contrato documenta, e é o que deixa a
            # mesma regra rodar sobre dataclass da fonte sintética e sobre dict
            # vindo de arquivo.
            consome=frozenset({self.esquerda, self.direita}),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(resolutions=self._casar(work))

    def _chave(self, payload: Any, lado: str) -> tuple[Any, ...] | None:
        """A chave de casamento, ou `None` se algum campo está vazio.

        Campo vazio NÃO casa: `None == None` seria verdade, e dois itens sem
        documento passariam a casar um com o outro por não terem documento —
        um falso positivo fabricado pela ausência de dado, que é o tipo de erro
        que este produto conta como zero falso positivo.
        """
        valores = []
        for par in self.pares:
            nome = par.esquerda if lado == "esq" else par.direita
            v = valor_do_campo(payload, nome)
            if v is None:
                return None
            if par.esquerda in self.modulo:
                v = abs(v)
            valores.append(v)
        return tuple(valores)

    def _casar(self, work: WorkSet) -> list[Resolution]:
        indice: dict[tuple[Any, ...], list[str]] = {}
        for item in work.of_kind(self.direita):
            chave = self._chave(item.payload, "dir")
            if chave is not None:
                indice.setdefault(chave, []).append(item.id)

        resultados: list[Resolution] = []
        usados: set[str] = set()
        for item in work.of_kind(self.esquerda):
            chave = self._chave(item.payload, "esq")
            if chave is None:
                continue
            candidatos = [i for i in indice.get(chave, []) if i not in usados]
            if not candidatos:
                continue
            # O PRIMEIRO livre ganha, e a escolha é a mesma de `ExactMatcher`.
            # Com vários candidatos idênticos não há critério melhor — eles são
            # indistinguíveis pelos campos comparados —, e a ordem do pool é
            # estável, então o resultado é reproduzível.
            escolhido = candidatos[0]
            usados.add(escolhido)
            resultados.append(
                Resolution(
                    item_ids=frozenset({item.id, escolhido}),
                    produced_by=self.name,
                    rule=f"igualdade: {', '.join(str(p) for p in self.pares)}",
                    evidence=dict(
                        zip((p.esquerda for p in self.pares), chave, strict=True)
                    ),
                )
            )
        return resultados


__all__ = ["Igualdade"]
