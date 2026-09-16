"""As sete regras da política, uma a uma, e a ordem entre elas.

Nada aqui importa domínio: a política é do kernel, e os dois predicados que o
domínio fornece (`value_at_risk`, `estimated_cost`) são `Callable`s injetados.
"""

import pytest

from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.policy import (
    Autonomy,
    Budget,
    ExecutionPolicy,
    PolicyContext,
    Route,
)
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.runtime import policy_engine
from orchestrator.runtime.engine import execute


class _R:
    def __init__(self, name="r", cost_class=CostClass.REGRA, resolve_tudo=False):
        self.name, self.cost_class, self._tudo = name, cost_class, resolve_tudo

    def describe(self):
        return ResolverDescription(self.name, self.cost_class, "t")

    def resolve(self, work):
        if not self._tudo:
            return ResolverOutput()
        return ResolverOutput(
            resolutions=[
                Resolution(item_ids=frozenset({i.id}), produced_by=self.name, rule="t")
                for i in work.items
            ]
        )


def _pool(*ids, valor=None):
    return WorkSet(items=tuple(WorkItem(id=i, kind="k", payload=valor) for i in ids))


def _ctx(**kw):
    return PolicyContext(model="claude-opus-5", **kw)


# --------------------------------------------------------------------------
# Regras 1 a 5 — este RESOLVER roda?
# --------------------------------------------------------------------------


def test_regra1_classe_acima_do_teto_pula():
    d = policy_engine.decide(
        _R(cost_class=CostClass.AGENTE),
        ExecutionPolicy(max_cost_class=CostClass.REGRA),
        _ctx(),
    )
    assert d.route is Route.PULAR
    assert "teto" in d.reason


def test_regra2_orcamento_estourado_PARA_e_nao_pula():
    """PARAR, não PULAR, e a diferença não é estética.

    Orçamento estourado não melhora com o próximo resolver — ele é mais caro,
    pela ordem da cascata. Já "classe acima do teto" é específico daquele
    resolver, e o próximo pode caber.
    """
    d = policy_engine.decide(
        _R(),
        ExecutionPolicy(budget=Budget(per_run_microcents=100)),
        _ctx(spent=Cost(input_tokens=1000)),
    )
    assert d.route is Route.PARAR
    assert "orçamento" in d.reason


def test_regra3_cancelamento_para():
    d = policy_engine.decide(_R(), ExecutionPolicy(), _ctx(cancelled=True))
    assert d.route is Route.PARAR


def test_regra4_autonomia_OBSERVAR_nunca_executa_classe_paga():
    """O `--dry-run` da CLI, garantido pela REGRA e não por uma flag."""
    politica = ExecutionPolicy(autonomy=Autonomy.OBSERVAR)

    assert policy_engine.decide(_R(), politica, _ctx()).route is Route.EXECUTAR
    for classe in (CostClass.AGENTE, CostClass.CREW, CostClass.HUMANO):
        d = policy_engine.decide(_R(cost_class=classe), politica, _ctx())
        assert d.route is Route.PULAR, classe


def test_regra5_indisponibilidade_pula_com_motivo():
    d = policy_engine.decide(
        _R(name="agente"),
        ExecutionPolicy(),
        _ctx(unavailable=lambda nome: "sem credencial" if nome == "agente" else None),
    )
    assert d.route is Route.PULAR
    assert "sem credencial" in d.reason


def test_ordem_das_regras_e_fixa_classe_vence_orcamento():
    """A primeira que casa vence, e a ordem é testada.

    Não há prioridade configurável — prioridade configurável é como uma
    política vira inauditável: quem lê um `PolicyDecision` precisa reconstruir
    a decisão sem saber em que ordem alguém configurou as regras naquele dia.
    """
    d = policy_engine.decide(
        _R(cost_class=CostClass.AGENTE),
        ExecutionPolicy(
            max_cost_class=CostClass.REGRA, budget=Budget(per_run_microcents=0)
        ),
        _ctx(spent=Cost(input_tokens=99999)),
    )
    assert "teto" in d.reason  # regra 1, não a 2


def test_sem_nenhuma_regra_impedindo_executa():
    d = policy_engine.decide(_R(), ExecutionPolicy(), _ctx())
    assert d.route is Route.EXECUTAR
    assert d.reason == "nenhuma regra impediu"


# --------------------------------------------------------------------------
# Regras 6 e 7 — sobre QUAIS itens?
# --------------------------------------------------------------------------


def test_politica_sem_predicado_devolve_o_pool_INTEIRO_e_nenhuma_decisao():
    """O caminho de `POLITICA_ATUAL`, e a razão de o motor de política entrar
    sem mudar um único número."""
    work = _pool("a", "b")

    elegiveis, decisoes = policy_engine.filtrar(_R(), work, ExecutionPolicy(), _ctx())

    assert elegiveis is work
    assert decisoes == []


def test_regra7_pula_item_cujo_custo_excede_a_fracao_do_valor():
    """A tese numa linha: não gaste US$ 0,04 para investigar R$ 0,30."""
    caro = WorkItem(id="caro", kind="k", payload=1_000_000_000)
    barato = WorkItem(id="barato", kind="k", payload=1_000)
    work = WorkSet(items=(caro, barato))

    elegiveis, decisoes = policy_engine.filtrar(
        _R(cost_class=CostClass.AGENTE),
        work,
        ExecutionPolicy(max_cost_ratio=0.02),
        _ctx(value_at_risk=lambda i: i.payload, estimated_cost=lambda _: 4_000_000),
    )

    assert [i.id for i in elegiveis.items] == ["caro"]
    assert decisoes[0].item_id == "barato"
    assert "valor em risco" in decisoes[0].reason
    # A evidência é o que a tela precisa para dizer quanto economizou.
    assert decisoes[0].evidence["estimado_microcents"] == 4_000_000


def test_regra7_NAO_se_aplica_a_resolver_de_graca():
    """Uma regra que não custa deve rodar sobre tudo, sempre.

    Sem esta guarda, um item de valor baixo sairia até do L1 — e a cascata
    barata, que é o que entrega os 85,3%, pararia de ver metade do pool.
    """
    work = _pool("barato", valor=1)

    elegiveis, decisoes = policy_engine.filtrar(
        _R(cost_class=CostClass.REGRA),
        work,
        ExecutionPolicy(max_cost_ratio=0.02),
        _ctx(value_at_risk=lambda i: 1, estimated_cost=lambda _: 4_000_000),
    )

    assert len(elegiveis.items) == 1
    assert decisoes == []


def test_valor_em_risco_None_desliga_a_regra_em_vez_de_aprovar_tudo():
    """Não se aplicar é diferente de aplicar e passar.

    Um domínio sem valor monetário (`domains/swe`) devolve `None` sempre, e a
    regra some — em vez de comparar contra zero e pular tudo.
    """
    work = _pool("x")

    elegiveis, decisoes = policy_engine.filtrar(
        _R(cost_class=CostClass.AGENTE),
        work,
        ExecutionPolicy(max_cost_ratio=0.02),
        _ctx(value_at_risk=lambda i: None, estimated_cost=lambda _: 4_000_000),
    )

    assert len(elegiveis.items) == 1
    assert decisoes == []


def test_predicado_de_dominio_pula_com_motivo_registrado():
    work = _pool("a", "b")

    elegiveis, decisoes = policy_engine.filtrar(
        _R(cost_class=CostClass.AGENTE),
        work,
        ExecutionPolicy(skip_when=lambda item, ctx: item.id == "a"),
        _ctx(),
    )

    assert [i.id for i in elegiveis.items] == ["b"]
    assert decisoes[0].item_id == "a"


# --------------------------------------------------------------------------
# A invariante que a política NÃO pode quebrar
# --------------------------------------------------------------------------


def test_nenhuma_politica_consegue_inverter_a_ordem_de_custo():
    """A invariante nº 2 do §1.5.

    `Stage.ordered()` é a ORDEM; a política decide se cada resolver DA ORDEM
    roda. As duas são ortogonais, e é isso que impede a política de chamar
    inteligência antes da regra de graça.

    Não há `ExecutionPolicy` que faça o agente rodar antes do L1 — não porque
    alguém valida, mas porque a política não tem campo que expresse ordem.
    """
    cascata = (_R("agente", CostClass.AGENTE), _R("L1", CostClass.REGRA))
    for politica in (
        ExecutionPolicy(),
        ExecutionPolicy(autonomy=Autonomy.AGIR, max_cost_class=CostClass.HUMANO),
        ExecutionPolicy(max_cost_ratio=0.99),
    ):
        stage = Stage("s", cascata, policy=politica)
        assert [r.name for r in stage.ordered()] == ["L1", "agente"]

    assert not any(
        "ordem" in c or "order" in c for c in ExecutionPolicy.__dataclass_fields__
    )


def test_a_politica_NAO_entra_na_versao_do_workflow():
    """Ela é variável de EXPERIMENTO (§14.4).

    Rodar o mesmo workflow com duas políticas tem de produzir a mesma
    `workflow_version`, ou o benchmark de M6 compararia dois workflows em vez
    de duas políticas. A política é observável pelo `Run`, em
    `policy_decisions`.
    """
    cascata = (_R(),)
    a = WorkflowDefinition("w", "W", (Stage("s", cascata, policy=ExecutionPolicy()),))
    b = WorkflowDefinition(
        "w", "W", (Stage("s", cascata, policy=ExecutionPolicy(max_cost_ratio=0.5)),)
    )

    assert a.version == b.version


def test_orcamento_negativo_falha_na_construcao():
    # Teto negativo faria a primeira comparação já nascer estourada: tudo
    # pularia sem nunca rodar, e pareceria política funcionando com orçamento
    # zerado em vez de configuração inválida.
    with pytest.raises(ValueError, match="não pode ser negativo"):
        Budget(per_run_microcents=-1)


# --------------------------------------------------------------------------
# Integração com o motor
# --------------------------------------------------------------------------


def test_o_run_registra_POR_QUE_cada_resolver_rodou_ou_nao():
    """Sem este registro, "a política pulou o agente" é indistinguível de "o
    agente não achou nada" — a mesma ambiguidade que `proposals_api_failed`
    elimina em `agent_eval.py`."""
    definicao = WorkflowDefinition(
        id="w",
        name="W",
        stages=(
            Stage(
                "s",
                (_R("L1"), _R("agente", CostClass.AGENTE)),
                policy=ExecutionPolicy(max_cost_class=CostClass.REGRA),
            ),
        ),
    )

    run = execute(definicao, _pool("a"))

    por_resolver = {d.resolver_name: d for d in run.policy_decisions}
    assert por_resolver["L1"].route is Route.EXECUTAR
    assert por_resolver["agente"].route is Route.PULAR


def test_PARAR_encerra_o_stage_e_nao_so_pula_um_resolver():
    definicao = WorkflowDefinition(
        id="w",
        name="W",
        stages=(Stage("s", (_R("L1"), _R("L2"), _R("L3"))),),
    )

    run = execute(
        definicao, _pool("a"), policy=_ctx(cancelled=True), model="claude-opus-5"
    )

    # A primeira decisão já PARA; L2 e L3 nem são consultados.
    assert len(run.policy_decisions) == 1
    assert run.policy_decisions[0].route is Route.PARAR
