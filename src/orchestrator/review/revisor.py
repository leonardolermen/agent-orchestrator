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
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.models import PAYLOADS, conciliacao, divergencias, lados
from orchestrator.review.fila import Fila


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
            payloads=PAYLOADS,
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        matches: list[Resolution] = []
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
        for divergencia in divergencias(work):
            decisao = self.fila.decisao(divergencia.id)
            if decisao is None or not decisao.concilia:
                continue

            citados = (
                set(divergencia.bank_ids)
                | set(divergencia.ledger_ids)
                | set(decisao.conciliar_com)
            )
            # Se algum id citado já foi consumido por uma decisão anterior
            # nesta passagem, a decisão inteira é obsoleta — mesma regra de
            # tudo-ou-nada do id fantasma abaixo.
            if consumidos & citados:
                continue
            # O lado de cada id vem do POOL, nunca do prefixo do id nem do
            # tipo da divergência. Um id que não está em nenhum dos dois lados
            # é obsoleto, e a decisão inteira é descartada — emitir um vínculo
            # parcial seria fabricar ligação com id fantasma.
            #
            # `lados()` responde as duas coisas de uma vez: o que é de cada
            # lado, e (pelo que sobra) o que não está no pool. A checagem
            # deixou de ser um laço com `break`; a REGRA é a mesma.
            de_banco, de_contabil = lados(work, frozenset(citados))
            if len(de_banco) + len(de_contabil) != len(citados):
                continue
            if not de_banco or not de_contabil:
                continue

            consumidos.update(citados)
            matches.append(
                conciliacao(
                    work,
                    frozenset(citados),
                    produced_by=self.name,
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
        return ResolverOutput(resolutions=matches, cost=Cost.zero())
