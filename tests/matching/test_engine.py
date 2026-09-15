from random import Random

from orchestrator.agent.proposal import Cost, InvestigationOutput, Proposal
from orchestrator.matching.engine import default_matchers, reconcile
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal, DevolucaoFundos


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


def test_matchers_sao_injetaveis():
    pares = generate_clean_pairs(seed=8, n=5)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger, matchers=[])

    assert r.matches == []
    assert len(r.divergences) > 0


def test_default_matchers_tem_tres_camadas():
    assert [m.layer for m in default_matchers()] == ["L1", "L2", "L3"]


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
