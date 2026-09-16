"""O resolver de classe HUMANO: decisão vira vínculo.

O §4.4 do spec de composição: aprovação humana não é feature especial, é o
último resolver de uma cascata. Nenhum mecanismo novo, nenhum modo de execução
separado.

Este módulo só LÊ a fila. Quem grava é o CLI (propostas) e a API (decisões) —
`reconcile` continua puro, e é disso que o golden e o teste do dinheiro
dependem.
"""

from dataclasses import dataclass, field

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.models import MatchResult
from orchestrator.review.fila import Fila
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
        # `no_banco`/`no_contabil` são o pool no INÍCIO da passagem: `work` só
        # encolhe entre passagens, via `WorkSet.without()` depois que
        # `resolve()` retorna — nunca durante o laço. Por isso um id que uma
        # decisão já consumiu NESTA passagem continua parecendo disponível
        # para a próxima; sem guarda própria, duas decisões que citam o mesmo
        # id (o caso do fantasma: `d-b-b00003` e `d-l-l00003` do mesmo par)
        # virariam dois matches para um único par. `consumidos` é o `usados`
        # de `ExactMatcher._casar` aplicado aqui: cada id só entra em um
        # match por passagem.
        consumidos: set[str] = set()
        # Itera o POOL, não o log de decisões: `fila.decisao(id)` lê
        # `_decisoes` direto, sem exigir que exista uma proposta casada em
        # `_ordem` (é o que `decididas()` exige, e uma decisão pode chegar
        # sem proposta prévia). Uma divergência sem decisão, cuja decisão cita
        # ids que não estão mais no pool, ou cujos ids já saíram por uma
        # decisão anterior nesta mesma passagem, simplesmente não aparece
        # aqui — é assim que "decisão obsoleta" (regra resolveu antes, id fora
        # do pool; ou outra decisão já fechou o caso, id em `consumidos`) vira
        # silêncio em vez de erro.
        for divergencia in work.as_divergences():
            decisao = self.fila.decisao(divergencia.id)
            if decisao is None or not decisao.concilia:
                continue

            bank = set(divergencia.bank_ids)
            ledger = set(divergencia.ledger_ids)
            # Se o próprio id da divergência ou algum id citado em
            # `conciliar_com` já foi consumido por uma decisão anterior nesta
            # passagem, a decisão inteira é obsoleta — mesma regra de
            # tudo-ou-nada do id fantasma abaixo.
            if consumidos & (bank | ledger | decisao.conciliar_com):
                continue
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

            consumidos.update(bank)
            consumidos.update(ledger)
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
