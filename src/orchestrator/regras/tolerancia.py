"""Casar dois lados com folga: chave exata, mais uma diferença que se aceita.

É a forma de `ToleranceMatcher` (o L2 da conciliação) sem os campos cravados:
agrupa a direita por uma chave exata e, dentro do grupo, aceita o primeiro
candidato cuja diferença numérica — e, se pedida, temporal — cabe na folga.

**O que esta regra NÃO consegue ser, e é bom dizer alto.** O L2 da conciliação
mede prazo em DIAS ÚTEIS do calendário bancário brasileiro
(`domains/reconciliation/dates.py`). Dia útil não é propriedade dos dados: é
conhecimento de domínio sobre feriado e fim de semana, e nenhuma configuração
de tela o produz. Esta regra conta dias CORRIDOS. Por isso ela generaliza a
forma do L2 sem substituí-lo — e o L2 continua no domínio, que é a resposta
honesta para onde a fronteira entre genérico e específico realmente passa.
"""

from dataclasses import dataclass, field
from typing import Any

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.regras.campos import valor_do_campo
from orchestrator.regras.pares import Par, interpretar, interpretar_todos


@dataclass(frozen=True)
class Tolerancia:
    """Chave exata, valor com folga, e opcionalmente data com folga."""

    esquerda: str
    direita: str
    # Os campos que precisam bater EXATAMENTE para os dois virarem candidatos.
    # Sem chave, toda combinação seria candidata e a folga sozinha casaria
    # itens sem relação nenhuma — folga é desempate, não critério.
    chave: tuple[str, ...]
    # `"amount=net_amount"`. O campo cuja diferença absoluta precisa caber.
    numerico: str
    max_diferenca: int = 0
    # `|esq|` contra `|dir|` no campo numérico. Ver `Igualdade.modulo`.
    modulo: bool = False
    # `"date=cash_date"`, ou vazio para não impor condição temporal.
    data: str = ""
    # Dias CORRIDOS. Ver o docstring do módulo: dia útil é do domínio.
    max_dias: int = 0
    name: str = "tolerancia"
    resumo: str = "chave exata, com folga de valor e de dias corridos"
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_chave", interpretar_todos(self.chave))
        object.__setattr__(self, "_numerico", interpretar(self.numerico))
        object.__setattr__(
            self, "_data", interpretar(self.data) if self.data else None
        )
        # Folga negativa não casaria nada e pareceria uma regra que
        # simplesmente não encontrou nada — falha silenciosa disfarçada de
        # resultado. A recusa é a mesma de `ToleranceMatcher.__post_init__`.
        if self.max_diferenca < 0:
            raise ValueError(
                f"{self.name!r}: max_diferenca não pode ser negativo: "
                f"{self.max_diferenca}"
            )
        if self.max_dias < 0:
            raise ValueError(
                f"{self.name!r}: max_dias não pode ser negativo: {self.max_dias}"
            )
        if self.esquerda == self.direita:
            raise ValueError(
                f"{self.name!r}: os dois lados são o kind {self.esquerda!r}. um "
                f"item casaria consigo mesmo"
            )

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

    @property
    def _pares_chave(self) -> tuple[Par, ...]:
        return self._chave  # type: ignore[attr-defined]

    def _cabe(self, esq: Any, dir_: Any) -> dict[str, Any] | None:
        """A evidência da folga, ou `None` quando algum limite estourou."""
        par_num: Par = self._numerico  # type: ignore[attr-defined]
        a = valor_do_campo(esq, par_num.esquerda)
        b = valor_do_campo(dir_, par_num.direita)
        if a is None or b is None:
            return None
        diferenca = abs((abs(a) if self.modulo else a) - (abs(b) if self.modulo else b))
        if diferenca > self.max_diferenca:
            return None
        evidencia: dict[str, Any] = {"diferenca": diferenca}

        par_data: Par | None = self._data  # type: ignore[attr-defined]
        if par_data is not None:
            d1 = valor_do_campo(esq, par_data.esquerda)
            d2 = valor_do_campo(dir_, par_data.direita)
            if d1 is None or d2 is None:
                return None
            dias = abs((d2 - d1).days)
            if dias > self.max_dias:
                return None
            evidencia["dias"] = dias
        return evidencia

    def _casar(self, work: WorkSet) -> list[Resolution]:
        indice: dict[tuple[Any, ...], list[Any]] = {}
        for item in work.of_kind(self.direita):
            chave = self._chave_de(item.payload, "dir")
            if chave is not None:
                indice.setdefault(chave, []).append(item)

        resultados: list[Resolution] = []
        usados: set[str] = set()
        for item in work.of_kind(self.esquerda):
            chave = self._chave_de(item.payload, "esq")
            if chave is None:
                continue
            for candidato in indice.get(chave, []):
                if candidato.id in usados:
                    continue
                evidencia = self._cabe(item.payload, candidato.payload)
                if evidencia is None:
                    continue
                usados.add(candidato.id)
                resultados.append(
                    Resolution(
                        item_ids=frozenset({item.id, candidato.id}),
                        produced_by=self.name,
                        rule=(
                            f"tolerância: {', '.join(str(p) for p in self._pares_chave)} "
                            f"exatos, até {self.max_diferenca} de diferença"
                            + (f" e {self.max_dias} dias" if self._data else "")
                        ),
                        evidence=evidencia,
                    )
                )
                break
        return resultados


__all__ = ["Tolerancia"]
