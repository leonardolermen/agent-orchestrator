"""Camada L3: um lançamento bancário cobrindo N contábeis do mesmo fornecedor.

A busca por subconjuntos é exponencial, então é limitada por max_group_size e
por janela de data. Isso é deliberado: a camada determinística deve ser barata.
O que ela não alcançar é trabalho do agente, não motivo para relaxar o limite.
"""

from dataclasses import dataclass, field
from itertools import combinations

from orchestrator.dates import business_days_between
from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.models import LedgerEntry, banco, conciliacao, contabil


@dataclass
class GroupingMatcher:
    max_group_size: int = 4
    max_business_days: int = 3
    max_candidates: int = 24
    name: str = field(default="L3", init=False)
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        # Tamanho menor que 2 esvazia o range de combinações e a camada nunca
        # agrupa nada, sem erro e sem aviso.
        if self.max_group_size < 2:
            raise ValueError(
                f"agrupamento exige tamanho mínimo 2: {self.max_group_size}"
            )
        if self.max_business_days < 0:
            raise ValueError(
                f"max_business_days não pode ser negativo: {self.max_business_days}"
            )
        if self.max_candidates < self.max_group_size:
            raise ValueError(
                f"teto de candidatos ({self.max_candidates}) não pode ser menor que "
                f"o tamanho máximo de grupo ({self.max_group_size})"
            )

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary="um lançamento bancário cobrindo N contábeis do mesmo fornecedor",
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        return ResolverOutput(resolutions=self._casar(work))

    def _casar(self, work: WorkSet) -> list[Resolution]:
        bank, ledger = banco(work), contabil(work)
        por_fornecedor: dict[str, list[LedgerEntry]] = {}
        for le in ledger:
            if le.cash_date is not None:
                por_fornecedor.setdefault(le.supplier, []).append(le)

        resultados: list[Resolution] = []
        usados: set[str] = set()

        for be in bank:
            if be.counterparty is None:
                continue

            # Esta camada existe para casar PAGAMENTOS agregados. Um crédito é
            # recebimento e não deveria sair procurando faturas a pagar — sem
            # esta guarda, a perna de crédito de uma devolução de fundos entra
            # na busca e pode casar com faturas por coincidência de soma.
            if be.amount >= 0:
                continue

            candidatos = [
                le
                for le in por_fornecedor.get(be.counterparty, [])
                if le.id not in usados
                and le.cash_date is not None
                and business_days_between(be.date, le.cash_date) <= self.max_business_days
            ]
            if len(candidatos) < 2:
                continue

            # O custo da busca é O(C^max_group_size) no tamanho do pool, então
            # sem teto os dois botões desta camada não limitam nada: com algumas
            # centenas de candidatos a busca explode. O teto também reduz falso
            # positivo, porque pool maior é mais oportunidade de uma soma
            # coincidir por acaso. Estourou, o lançamento vira divergência — que
            # é o destino previsto de tudo que a camada barata não resolve.
            if len(candidatos) > self.max_candidates:
                continue

            alvo = abs(be.amount)
            grupo = self._encontrar_grupo(candidatos, alvo)
            if grupo is None:
                continue

            usados.update(le.id for le in grupo)
            resultados.append(
                conciliacao(
                    work,
                    frozenset({be.id, *(le.id for le in grupo)}),
                    produced_by=self.name,
                    rule=(
                        f"agrupamento: soma de {len(grupo)} líquidos do mesmo "
                        f"fornecedor iguala o lançamento bancário"
                    ),
                    evidence={
                        "fornecedor": be.counterparty,
                        "quantidade": len(grupo),
                        "soma": alvo,
                        "documentos": sorted(le.document or le.id for le in grupo),
                        # A soma sozinha não é auditável: "estes valores somam
                        # este total" só se verifica com os valores
                        # individuais. Chaveado por documento (ou id, na
                        # ausência) para bater com a lista acima.
                        "valores_por_documento": {
                            (le.document or le.id): le.net_amount for le in grupo
                        },
                    },
                )
            )

        return resultados

    def _encontrar_grupo(
        self, candidatos: list[LedgerEntry], alvo: int
    ) -> tuple[LedgerEntry, ...] | None:
        limite = min(self.max_group_size, len(candidatos))
        for tamanho in range(2, limite + 1):
            for combinacao in combinations(candidatos, tamanho):
                if sum(le.net_amount for le in combinacao) == alvo:
                    return combinacao
        return None
