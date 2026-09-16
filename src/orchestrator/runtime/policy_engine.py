"""As sete regras, em ordem fixa. A primeira que casa vence.

A ordem é FIXA e testada, e não há prioridade configurável — porque prioridade
configurável é como uma política vira inauditável. Quem lê um `PolicyDecision`
precisa poder reconstruir a decisão sem saber em que ordem alguém configurou as
regras naquele dia.

**Dois níveis, e a distinção importa.** Regras 1–5 decidem se um RESOLVER roda;
regras 6–7 decidem se ele roda sobre um ITEM. O motor pergunta as duas coisas em
momentos diferentes: a primeira antes de chamar o resolver, a segunda para
estreitar o pool que ele recebe.
"""

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.policy import (
    Autonomy,
    ExecutionPolicy,
    PolicyContext,
    PolicyDecision,
    Route,
)
from orchestrator.kernel.resolver import Resolver
from orchestrator.kernel.work import WorkSet


def _d(resolver: str, route: Route, reason: str, **evidence) -> PolicyDecision:
    return PolicyDecision(
        resolver_name=resolver, route=route, reason=reason, evidence=evidence
    )


def decide(
    resolver: Resolver, policy: ExecutionPolicy, ctx: PolicyContext
) -> PolicyDecision:
    """Este resolver roda? Regras 1 a 5, na ordem.

    `PARAR` encerra o stage; `PULAR` passa para o próximo resolver. A diferença
    não é estética: orçamento estourado não melhora com o próximo resolver (que
    é mais caro, pela ordem), enquanto "classe acima do teto" é específico
    daquele resolver.
    """
    nome = resolver.name

    # 1. TETO DE CLASSE — nunca suba acima do autorizado.
    if resolver.cost_class > policy.max_cost_class:
        return _d(
            nome,
            Route.PULAR,
            "classe acima do teto da política",
            classe=resolver.cost_class.name,
            teto=policy.max_cost_class.name,
        )

    # 2. ORÇAMENTO — o teto é duro, e estourar é evento, não exceção.
    estourado = policy.budget.exceeded_by(ctx.spent, ctx.model, ctx.elapsed_ms)
    if estourado is not None:
        return _d(nome, Route.PARAR, f"orçamento esgotado: {estourado}")

    # 3. CANCELAMENTO — cooperativo, checado entre resolvers. Matar uma thread
    #    no meio de uma chamada HTTP deixaria custo gasto e não contabilizado.
    if ctx.cancelled:
        return _d(nome, Route.PARAR, "cancelado")

    # 4. AUTONOMIA — OBSERVAR registra o que faria, e não gasta.
    if policy.autonomy is Autonomy.OBSERVAR and resolver.cost_class > CostClass.REGRA:
        return _d(
            nome,
            Route.PULAR,
            "autonomia OBSERVAR não executa classe paga",
            classe=resolver.cost_class.name,
        )

    # 5. DISPONIBILIDADE — sem credencial, sem provider, sem revisor de plantão.
    if ctx.unavailable is not None and (motivo := ctx.unavailable(nome)):
        return _d(nome, Route.PULAR, f"indisponível: {motivo}")

    return _d(nome, Route.EXECUTAR, "nenhuma regra impediu")


def filtrar(
    resolver: Resolver, work: WorkSet, policy: ExecutionPolicy, ctx: PolicyContext
) -> tuple[WorkSet, list[PolicyDecision]]:
    """Sobre QUAIS itens este resolver roda? Regras 6 e 7, por item.

    Devolve o pool estreitado e uma decisão por item excluído — nunca uma
    exclusão silenciosa. Um item que sai daqui sai com motivo registrado, e é
    isso que permite à tela dizer "a política pulou o agente em 12 itens,
    economia estimada US$ 0,048".

    **Sem predicados e sem `max_cost_ratio`, devolve o pool INTEIRO e nenhuma
    decisão.** É o caminho de `POLITICA_ATUAL`, e é por isso que o motor de
    política entra sem mudar um único número.
    """
    if (
        policy.skip_when is None
        and policy.escalate_when is None
        and policy.max_cost_ratio is None
    ):
        return work, []

    manter, decisoes = [], []
    for item in work.items:
        motivo = _por_que_pular(item, resolver, policy, ctx)
        if motivo is None:
            manter.append(item)
            continue
        decisoes.append(
            PolicyDecision(
                resolver_name=resolver.name,
                route=motivo[0],
                reason=motivo[1],
                item_id=item.id,
                evidence=motivo[2],
            )
        )
    return WorkSet(items=tuple(manter)), decisoes


def _por_que_pular(item, resolver, policy, ctx):
    """`None` para executar; `(rota, motivo, evidência)` para não."""
    # 6. PREDICADO DE DOMÍNIO — escalar antes de gastar.
    if policy.escalate_when is not None and policy.escalate_when(item, ctx):
        return (Route.PULAR, "escalado pelo predicado do domínio", {})
    if policy.skip_when is not None and policy.skip_when(item, ctx):
        return (Route.PULAR, "pulado pelo predicado do domínio", {})

    # 7. VIABILIDADE ECONÔMICA — a regra que a tese pede.
    #    Não gaste US$ 0,04 para investigar uma divergência de R$ 0,30.
    #
    #    Só vale para resolver que CUSTA: uma regra de graça deve rodar sobre
    #    tudo, sempre. Sem esta guarda, um item de valor baixo sairia até do L1.
    if policy.max_cost_ratio is None or resolver.cost_class <= CostClass.REGRA:
        return None
    if ctx.value_at_risk is None or ctx.estimated_cost is None:
        return None
    valor = ctx.value_at_risk(item)
    if valor is None:
        # A regra não se aplica a este item. Não se aplicar é diferente de
        # aplicar e passar — um domínio sem valor monetário (SWE) devolve
        # `None` sempre, e a regra some em vez de aprovar tudo por engano.
        return None
    estimado = ctx.estimated_cost(resolver.name)
    if estimado > valor * policy.max_cost_ratio:
        return (
            Route.PULAR,
            f"custo estimado excede {policy.max_cost_ratio:.0%} do valor em risco",
            {"estimado_microcents": estimado, "valor_em_risco": valor},
        )
    return None
