from random import Random

from orchestrator.agent.proposal import Cost, InvestigationOutput, Proposal
from orchestrator.cli import build_benchmark
from orchestrator.matching.engine import default_resolvers, reconcile
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal, DevolucaoFundos
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.resolver import ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet

# Benchmark pequeno com divergências garantidas: n=60 na semente 1 produz 6
# divergências, o suficiente para os testes de pool não serem degenerados.
_DATASET_DE_TESTE = build_benchmark(seed=1, n=60, taxa_divergencia=0.15)
BANCO_DE_TESTE = _DATASET_DE_TESTE.bank
CONTABIL_DE_TESTE = _DATASET_DE_TESTE.ledger


def test_dataset_limpo_nao_gera_divergencia():
    pares = generate_clean_pairs(seed=8, n=30)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger)

    assert r.divergences == []
    assert len(r.matches) == 30


def test_camadas_sao_aplicadas_em_ordem():
    pares = generate_clean_pairs(seed=8, n=10)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger)

    # tudo limpo deve ser resolvido na camada mais barata
    assert {m.layer for m in r.matches} == {"L1"}


def test_defasagem_grande_vira_divergencia():
    pares = generate_clean_pairs(seed=8, n=5)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger)

    ids_divergentes = {i for d in r.divergences for i in d.bank_ids | d.ledger_ids}
    assert inj.bank[0].id in ids_divergentes


def test_devolucao_vira_divergencia_com_todas_as_pernas():
    pares = generate_clean_pairs(seed=8, n=5)
    inj = DevolucaoFundos().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger)

    ids_divergentes = {i for d in r.divergences for i in d.bank_ids}
    assert all(e.id in ids_divergentes for e in inj.bank)


def test_nenhum_lancamento_aparece_em_match_e_divergencia():
    pares = generate_clean_pairs(seed=8, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger)

    casados = {i for m in r.matches for i in m.bank_ids | m.ledger_ids}
    divergentes = {i for d in r.divergences for i in d.bank_ids | d.ledger_ids}
    assert casados & divergentes == set()


def test_resolvers_sao_injetaveis():
    pares = generate_clean_pairs(seed=8, n=5)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger, resolvers=[])

    assert r.matches == []
    assert len(r.divergences) > 0


def test_default_resolvers_tem_tres_camadas():
    assert [r.name for r in default_resolvers()] == ["L1", "L2", "L3"]


class _InvestigadorFalso:
    name = "falso"

    def __init__(self):
        self.recebeu = None

    def investigate(self, divergences):
        self.recebeu = divergences
        return InvestigationOutput(
            proposals=[Proposal.abstencao(d.id, "teste") for d in divergences],
            cost=Cost(calls=len(divergences)),
        )


def test_sem_investigador_nao_ha_propostas():
    pares = generate_clean_pairs(seed=8, n=10)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger)

    assert r.proposals == []
    assert r.agent_cost == Cost.zero()


def test_investigador_recebe_apenas_o_que_sobrou():
    pares = generate_clean_pairs(seed=8, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])
    espiao = _InvestigadorFalso()

    r = reconcile(ds.bank, ds.ledger, investigator=espiao)

    assert espiao.recebeu == r.divergences
    assert len(r.proposals) == len(r.divergences)


def test_proposta_nao_resolve_a_divergencia():
    # O item continua divergente até um humano aprovar. Se a proposta removesse
    # do pool, a taxa determinística passaria a contar trabalho do agente.
    pares = generate_clean_pairs(seed=8, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    sem = reconcile(ds.bank, ds.ledger)
    com = reconcile(ds.bank, ds.ledger, investigator=_InvestigadorFalso())

    assert len(com.divergences) == len(sem.divergences)
    assert len(com.matches) == len(sem.matches)


def test_custo_do_agente_e_agregado_no_resultado():
    pares = generate_clean_pairs(seed=8, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(ds.bank, ds.ledger, investigator=_InvestigadorFalso())

    assert r.agent_cost.calls == len(r.divergences)


class _ResolverEspiao:
    """Registra a ordem em que foi chamado. Não resolve nada."""

    def __init__(self, name: str, cost_class: CostClass, registro: list[str]) -> None:
        self.name = name
        self.cost_class = cost_class
        self._registro = registro

    def resolve(self, work: WorkSet) -> ResolverOutput:
        self._registro.append(self.name)
        return ResolverOutput()

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "espião")


def test_agente_roda_depois_da_regra_mesmo_declarado_antes():
    # A ordem entre classes de custo é DERIVADA, não escolhida. Não existe
    # lista de entrada que ponha o agente na frente da regra — é isso que faz
    # a armadilha cara deixar de ser um erro possível.
    registro: list[str] = []
    cascata = [
        _ResolverEspiao("agente", CostClass.AGENTE, registro),
        _ResolverEspiao("regra", CostClass.REGRA, registro),
    ]

    reconcile([], [], resolvers=cascata)

    assert registro == ["regra", "agente"]


def test_ordem_dentro_da_mesma_classe_e_preservada():
    # Dentro da mesma classe de custo a ordem é conhecimento de domínio do
    # especialista e tem que sobreviver. Isso depende de `sorted` ser estável.
    registro: list[str] = []
    cascata = [
        _ResolverEspiao("segunda", CostClass.REGRA, registro),
        _ResolverEspiao("primeira", CostClass.REGRA, registro),
    ]

    reconcile([], [], resolvers=cascata)

    assert registro == ["segunda", "primeira"]


def test_proposta_nao_remove_nada_do_pool():
    # Um resolver que só propõe não pode encolher o pool. Se encolher, o item
    # sai de divergente sem ninguém ter aprovado nada.
    from orchestrator.agent.proposal import Confidence, Proposal
    from orchestrator.taxonomy import DivergenceType

    class _SoPropoe:
        name = "propositor"
        cost_class = CostClass.AGENTE

        def resolve(self, work: WorkSet) -> ResolverOutput:
            return ResolverOutput(
                proposals=[
                    Proposal(
                        divergence_id=d.id,
                        tipo=DivergenceType.NAO_IDENTIFICADO,
                        explicacao="",
                        evidencia=[],
                        confianca=Confidence.BAIXA,
                        acao_sugerida="investigar_manual",
                    )
                    for d in work.as_divergences()
                ]
            )

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "só propõe")

    sem = reconcile(BANCO_DE_TESTE, CONTABIL_DE_TESTE, resolvers=[])
    com = reconcile(BANCO_DE_TESTE, CONTABIL_DE_TESTE, resolvers=[_SoPropoe()])

    assert len(com.divergences) == len(sem.divergences)
    assert len(com.proposals) == len(sem.divergences)
