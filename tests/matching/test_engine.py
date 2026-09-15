from random import Random

from orchestrator.agent.proposal import Cost, InvestigationOutput, Proposal
from orchestrator.cli import build_benchmark
from orchestrator.matching.engine import default_resolvers, reconcile
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal, DevolucaoFundos
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.definition import Stage, WorkflowDefinition
from orchestrator.workflow.resolver import Resolver, ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet

# Benchmark pequeno com divergências garantidas: n=60 na semente 1 produz 6
# divergências, o suficiente para os testes de pool não serem degenerados.
_DATASET_DE_TESTE = build_benchmark(seed=1, n=60, taxa_divergencia=0.15)
BANCO_DE_TESTE = _DATASET_DE_TESTE.bank
CONTABIL_DE_TESTE = _DATASET_DE_TESTE.ledger


def _definicao(cascade: list[Resolver]) -> WorkflowDefinition:
    """Uma WorkflowDefinition de um stage só, para os testes que antes
    passavam `resolvers=` direto para `reconcile`."""
    return WorkflowDefinition(
        id="teste", name="teste", stages=(Stage(name="teste", cascade=tuple(cascade)),)
    )


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

    r = reconcile(ds.bank, ds.ledger, definition=_definicao([]))

    assert r.matches == []
    assert len(r.divergences) > 0


def test_default_resolvers_tem_tres_camadas():
    assert [r.name for r in default_resolvers()] == ["L1", "L2", "L3"]


def test_default_resolvers_sao_todos_regra():
    # cost_class é a chave de ordenação da cascata. O golden não pega um
    # cost_class errado no L2, porque nesta configuração o L2 não casa nada:
    # a ordem mudaria e os oito campos congelados ficariam idênticos.
    assert [r.cost_class for r in default_resolvers()] == [CostClass.REGRA] * 3


def test_cada_resolver_se_descreve_com_o_proprio_nome_e_classe():
    for r in default_resolvers():
        d = r.describe()
        assert (d.name, d.cost_class) == (r.name, r.cost_class)
        assert d.summary


class _InvestigadorFalso:
    name = "falso"
    cost_class = CostClass.AGENTE

    def __init__(self):
        self.recebeu = None

    def investigate(self, divergences):
        self.recebeu = divergences
        return InvestigationOutput(
            proposals=[Proposal.abstencao(d.id, "teste") for d in divergences],
            cost=Cost(calls=len(divergences)),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        saida = self.investigate(work.as_divergences())
        return ResolverOutput(proposals=saida.proposals, cost=saida.cost)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "falso")


def test_sem_investigador_nao_ha_propostas():
    pares = generate_clean_pairs(seed=8, n=10)
    ds = build_dataset(pares, injections=[])

    r = reconcile(ds.bank, ds.ledger)

    assert r.proposals == []
    assert all(custo == Cost.zero() for custo in r.cost_by_resolver.values())


def test_investigador_recebe_apenas_o_que_sobrou():
    pares = generate_clean_pairs(seed=8, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])
    espiao = _InvestigadorFalso()

    r = reconcile(ds.bank, ds.ledger, definition=_definicao([*default_resolvers(), espiao]))

    assert espiao.recebeu == r.divergences
    assert len(r.proposals) == len(r.divergences)


def test_proposta_nao_resolve_a_divergencia():
    # O item continua divergente até um humano aprovar. Se a proposta removesse
    # do pool, a taxa determinística passaria a contar trabalho do agente.
    pares = generate_clean_pairs(seed=8, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    sem = reconcile(ds.bank, ds.ledger)
    com = reconcile(
        ds.bank, ds.ledger, definition=_definicao([*default_resolvers(), _InvestigadorFalso()])
    )

    assert len(com.divergences) == len(sem.divergences)
    assert len(com.matches) == len(sem.matches)


def test_custo_do_agente_e_agregado_no_resultado():
    pares = generate_clean_pairs(seed=8, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(
        ds.bank, ds.ledger, definition=_definicao([*default_resolvers(), _InvestigadorFalso()])
    )

    assert r.cost_by_resolver["falso"].calls == len(r.divergences)


def test_custo_de_dois_resolvers_na_cascata_e_somado_nao_sobrescrito_no_agent_cost():
    # Review do Task 5, round 2: com um resolver só, `custo_total = custo_total
    # + saida.cost` (certo) e a regressão `custo_total = saida.cost`
    # (sobrescreve em vez de somar) produzem o MESMO resultado — soma de um
    # único valor não-zero com `Cost.zero()` é o próprio valor, e o teste
    # anterior (`_AgenteFalso` sozinho, ou `_InvestigadorFalso` empilhado só
    # com regras que sempre custam zero) não distinguia as duas
    # implementações.
    #
    # Aqui são DOIS resolvers, os dois com custo não-zero e DISTINTO nos três
    # campos (input_tokens, output_tokens, calls). Cada um precisa aparecer em
    # `cost_by_resolver` com o PRÓPRIO custo, sem se misturar com o do outro; e
    # a soma dos dois (o que a tela usaria como total do sistema) só bate com o
    # valor esperado se for soma de verdade — overwrite faria um dos dois
    # "vencer" sozinho — e um bug parcial em `Cost.__add__` (um campo que
    # deixasse de ser somado) também apareceria, porque os três campos têm
    # valores diferentes entre A e B.
    class _AgenteFalsoA:
        name = "agente_falso_a"
        cost_class = CostClass.AGENTE

        def resolve(self, work: WorkSet) -> ResolverOutput:
            return ResolverOutput(cost=Cost(input_tokens=321, output_tokens=64, calls=6))

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "agente falso A")

    class _AgenteFalsoB:
        name = "agente_falso_b"
        cost_class = CostClass.AGENTE

        def resolve(self, work: WorkSet) -> ResolverOutput:
            return ResolverOutput(cost=Cost(input_tokens=100, output_tokens=7, calls=2))

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "agente falso B")

    r = reconcile(
        BANCO_DE_TESTE,
        CONTABIL_DE_TESTE,
        definition=_definicao([_AgenteFalsoA(), _AgenteFalsoB()]),
    )

    assert r.cost_by_resolver["agente_falso_a"] == Cost(
        input_tokens=321, output_tokens=64, calls=6
    )
    assert r.cost_by_resolver["agente_falso_b"] == Cost(
        input_tokens=100, output_tokens=7, calls=2
    )
    soma = sum(r.cost_by_resolver.values(), Cost.zero())
    assert soma.input_tokens == 321 + 100
    assert soma.output_tokens == 64 + 7
    assert soma.calls == 6 + 2


def test_agente_na_cascata_recebe_as_mesmas_divergencias_que_recebia_por_parametro():
    # Quando o agente roda por último, `work.as_divergences()` produz
    # exatamente a lista que o parâmetro `investigator=` entregava. Este teste
    # é o que autoriza remover o parâmetro.
    registro: list[list[str]] = []

    class _RegistraDivergencias:
        name = "espiao"
        cost_class = CostClass.AGENTE

        def resolve(self, work: WorkSet) -> ResolverOutput:
            registro.append([d.id for d in work.as_divergences()])
            return ResolverOutput()

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "espião")

    esperado = reconcile(BANCO_DE_TESTE, CONTABIL_DE_TESTE)
    reconcile(
        BANCO_DE_TESTE,
        CONTABIL_DE_TESTE,
        definition=_definicao([*default_resolvers(), _RegistraDivergencias()]),
    )

    assert registro == [[d.id for d in esperado.divergences]]


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

    reconcile([], [], definition=_definicao(cascata))

    assert registro == ["regra", "agente"]


def test_ordem_entre_e_dentro_das_classes_e_preservada():
    # Duas classes intercaladas na entrada, cada uma com dois resolvers fora
    # de ordem alfabética. Um único resultado certo mata qualquer variante
    # errada de uma vez: sem ordenação nenhuma, ordenação instável, ordenação
    # por nome, ou ordenação invertida — todas produziriam uma sequência
    # diferente de ["regra_b", "regra_a", "agente_b", "agente_a"].
    registro: list[str] = []
    cascata = [
        _ResolverEspiao("agente_b", CostClass.AGENTE, registro),
        _ResolverEspiao("regra_b", CostClass.REGRA, registro),
        _ResolverEspiao("agente_a", CostClass.AGENTE, registro),
        _ResolverEspiao("regra_a", CostClass.REGRA, registro),
    ]

    reconcile([], [], definition=_definicao(cascata))

    assert registro == ["regra_b", "regra_a", "agente_b", "agente_a"]


def test_ordenacao_e_por_stage_nao_global():
    # O stage 1 só tem um AGENTE; o stage 2 só tem uma REGRA. Uma ordenação
    # GLOBAL (sort sobre todos os resolvers da definição de uma vez, ignorando
    # os limites de stage) colocaria a regra do stage 2 — cost_class mais
    # barata — na frente do agente do stage 1, produzindo
    # ["s2_regra", "s1_agente"]. A ordenação correta é POR STAGE: dentro de
    # cada stage a cascata é ordenada por custo, mas um stage roda inteiro
    # antes do próximo começa, então o agente do stage 1 sempre roda primeiro.
    registro: list[str] = []
    definicao = WorkflowDefinition(
        id="teste",
        name="teste",
        stages=(
            Stage(name="s1", cascade=(_ResolverEspiao("s1_agente", CostClass.AGENTE, registro),)),
            Stage(name="s2", cascade=(_ResolverEspiao("s2_regra", CostClass.REGRA, registro),)),
        ),
    )

    reconcile([], [], definition=definicao)

    assert registro == ["s1_agente", "s2_regra"]


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

    sem = reconcile(BANCO_DE_TESTE, CONTABIL_DE_TESTE, definition=_definicao([]))
    com = reconcile(BANCO_DE_TESTE, CONTABIL_DE_TESTE, definition=_definicao([_SoPropoe()]))

    assert len(com.divergences) == len(sem.divergences)
    assert len(com.proposals) == len(sem.divergences)
