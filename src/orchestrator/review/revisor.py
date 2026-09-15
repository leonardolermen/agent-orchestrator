"""O resolver de classe HUMANO: decisão vira vínculo.

O §4.4 do spec de composição: aprovação humana não é feature especial, é o
último resolver de uma cascata. Nenhum mecanismo novo, nenhum modo de execução
separado.

Este módulo só LÊ a fila. Quem grava é o CLI (propostas) e a API (decisões) —
`reconcile` continua puro, e é disso que o golden e o teste do dinheiro
dependem.
"""

from dataclasses import dataclass, field

from orchestrator.agent.proposal import Cost
from orchestrator.models import MatchResult
from orchestrator.review.fila import Fila
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet


@dataclass
class RevisorHumano:
    fila: Fila

    name: str = field(default="revisor", init=False)
    cost_class: CostClass = field(default=CostClass.HUMANO, init=False)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            summary="aplica as decisões aprovadas na fila de revisão",
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        no_banco = {e.id for e in work.bank}
        no_contabil = {e.id for e in work.ledger}

        matches: list[MatchResult] = []
        # Itera o POOL, não o log de decisões: `fila.decisao(id)` lê
        # `_decisoes` direto, sem exigir que exista uma proposta casada em
        # `_ordem` (é o que `decididas()` exige, e uma decisão pode chegar
        # sem proposta prévia). Uma divergência sem decisão, ou cuja decisão
        # não está mais no pool, simplesmente não aparece aqui — é assim que
        # "decisão obsoleta" (regra resolveu antes, ou outra decisão já
        # fechou o caso) vira silêncio em vez de erro.
        for divergencia in work.as_divergences():
            decisao = self.fila.decisao(divergencia.id)
            if decisao is None or not decisao.concilia:
                continue

            bank = set(divergencia.bank_ids)
            ledger = set(divergencia.ledger_ids)
            # O lado de cada id vem do POOL, nunca do prefixo do id nem do
            # tipo da divergência. Um id que não está em nenhum dos dois lados
            # é obsoleto, e a decisão inteira é descartada — emitir um match
            # parcial seria fabricar vínculo com id fantasma.
            obsoleta = False
            for i in decisao.conciliar_com:
                if i in no_banco:
                    bank.add(i)
                elif i in no_contabil:
                    ledger.add(i)
                else:
                    obsoleta = True
                    break
            if obsoleta or not bank or not ledger:
                continue

            matches.append(
                MatchResult(
                    bank_ids=frozenset(bank),
                    ledger_ids=frozenset(ledger),
                    layer=self.name,
                    rule="decisão humana",
                    evidence={
                        "autor": decisao.autor,
                        "quando": decisao.quando.isoformat(),
                        "veredito": decisao.veredito.value,
                        "motivo": decisao.motivo,
                    },
                )
            )
        # Trabalho humano custa, mas não em tokens — e `Cost` só mede tokens.
        return ResolverOutput(matches=matches, cost=Cost.zero())
