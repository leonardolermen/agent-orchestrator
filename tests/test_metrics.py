from random import Random

from orchestrator.agent.proposal import Confidence, Cost, InvestigationOutput, Proposal
from orchestrator.cli import build_benchmark
from orchestrator.matching.engine import default_resolvers, reconcile
from orchestrator.metrics import evaluate
from orchestrator.models import MatchResult
from orchestrator.money import format_brl
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal, PagamentoAgregado
from orchestrator.workflow.cost_class import CostClass
from orchestrator.workflow.definition import Stage, WorkflowDefinition
from orchestrator.workflow.resolver import Resolver, ResolverDescription, ResolverOutput
from orchestrator.workflow.workset import WorkSet


def _definicao(cascade: list[Resolver]) -> WorkflowDefinition:
    """Uma WorkflowDefinition de um stage só, para os testes que antes
    passavam `resolvers=` direto para `reconcile`."""
    return WorkflowDefinition(
        id="teste", name="teste", stages=(Stage(name="teste", cascade=tuple(cascade)),)
    )


class _ResolverInvestigadorFalso:
    """Cobra um custo fixo por divergência recebida, sem investigar de
    verdade — só para o custo por resolver aparecer não-zero na métrica."""

    name = "investigador"
    cost_class = CostClass.AGENTE

    def resolve(self, work: WorkSet) -> ResolverOutput:
        divergencias = work.as_divergences()
        return ResolverOutput(
            proposals=[Proposal.abstencao(d.id, "teste") for d in divergencias],
            cost=Cost(input_tokens=100 * len(divergencias), calls=len(divergencias)),
        )

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "investigador falso")


def _investigador_falso() -> Resolver:
    return _ResolverInvestigadorFalso()


def _com_agente(investigador: Resolver) -> WorkflowDefinition:
    """A cascata padrão de regras com um investigador acoplado no fim."""
    return _definicao([*default_resolvers(), investigador])


def test_dataset_limpo_tem_taxa_total():
    pares = generate_clean_pairs(seed=9, n=40)
    ds = build_dataset(pares, injections=[])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.deterministic_rate == 1.0
    assert m.false_positives == 0


def test_conta_divergencias_do_gabarito():
    pares = generate_clean_pairs(seed=9, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.truth_divergences == 1


def test_falso_positivo_quando_casa_o_que_deveria_divergir():
    # Tolerância absurda faz L2 casar um caso que o gabarito diz ser divergente.
    from orchestrator.matching.tolerance import ToleranceMatcher

    pares = generate_clean_pairs(seed=9, n=5)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(
        ds.bank, ds.ledger, definition=_definicao([ToleranceMatcher(max_business_days=999)])
    )
    m = evaluate(ds, r)

    assert m.false_positives == 1


def test_taxa_fica_entre_zero_e_um():
    # Resolver hostil: devolve ids que não existem no dataset. `resolvers` é um
    # ponto de extensão anunciado (reconcile aceita qualquer lista), então um
    # resolver com bug ou malicioso é um cenário alcançável, não hipotético.
    # Sem interseção com o dataset real, cada "casamento" fantasma infla o
    # numerador sem tocar o denominador — a taxa passa de 1.0 sem limite.
    class ResolverHostil:
        name = "HOSTIL"
        cost_class = CostClass.REGRA

        def resolve(self, work: WorkSet) -> ResolverOutput:
            # Mais ids fantasma que lançamentos reais no dataset: se o código
            # não intersectar com o dataset, o numerador ultrapassa o
            # denominador e a taxa passa de 1.0.
            return ResolverOutput(
                matches=[
                    MatchResult(
                        bank_ids=frozenset({f"id-fora-do-dataset-{i}" for i in range(10)}),
                        ledger_ids=frozenset(
                            {f"outro-id-fora-do-dataset-{i}" for i in range(10)}
                        ),
                        layer=self.name,
                        rule="finge casar ids que não existem no dataset",
                        evidence={},
                    )
                ]
            )

    pares = generate_clean_pairs(seed=9, n=2)
    ds = build_dataset(pares, injections=[])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger, definition=_definicao([ResolverHostil()])))

    assert 0.0 <= m.deterministic_rate <= 1.0


def test_cobertura_por_tipo_lista_os_tipos_injetados():
    pares = generate_clean_pairs(seed=9, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.truth_by_type["DEFASAGEM_TEMPORAL"] == 1


def test_agregado_resolvido_por_l3_nao_e_falso_positivo():
    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.false_positives == 0
    assert m.false_negatives == 0


def test_falso_negativo_quando_camada_nao_resolve_o_que_deveria():
    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    # sem nenhuma camada, o agregado deixa de ser resolvido
    m = evaluate(ds, reconcile(ds.bank, ds.ledger, definition=_definicao([])))

    assert m.false_negatives == 1


def test_valores_somam_o_total_do_extrato():
    pares = generate_clean_pairs(seed=9, n=25)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.matched_amount + m.divergent_amount == sum(abs(e.amount) for e in ds.bank)


def test_render_formata_valores_em_reais():
    # A versão anterior só checava "R$" em algum lugar da saída — passaria
    # mesmo com os dois campos trocados ou zerados. Aqui os dois valores são
    # diferentes de propósito, e cada um precisa aparecer na linha certa.
    pares = generate_clean_pairs(seed=9, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))
    linhas = m.render().splitlines()

    linha_conciliado = next(linha for linha in linhas if linha.startswith("Valor conciliado"))
    linha_divergencia = next(
        linha for linha in linhas if linha.startswith("Valor em divergência")
    )

    assert m.matched_amount != m.divergent_amount
    assert format_brl(m.matched_amount) in linha_conciliado
    assert format_brl(m.divergent_amount) in linha_divergencia
    assert format_brl(m.divergent_amount) not in linha_conciliado
    assert format_brl(m.matched_amount) not in linha_divergencia


def test_resolucao_parcial_de_agregado_conta_falso_negativo():
    # Um agregado só está resolvido se TODOS os seus ids foram casados. Casar
    # um dos três e deixar dois em divergência é falha parcial, e contar isso
    # como resolvido esconderia exatamente o que esta métrica existe para expor.
    class ResolverParcial:
        name = "PARCIAL"
        cost_class = CostClass.REGRA

        def resolve(self, work: WorkSet) -> ResolverOutput:
            if not work.bank or not work.ledger:
                return ResolverOutput()
            return ResolverOutput(
                matches=[
                    MatchResult(
                        bank_ids=frozenset({work.bank[0].id}),
                        ledger_ids=frozenset({work.ledger[0].id}),
                        layer=self.name,
                        rule="casa só um dos contábeis, de propósito",
                        evidence={},
                    )
                ]
            )

    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger, definition=_definicao([ResolverParcial()])))

    assert m.false_negatives == 1


def test_separa_casos_do_gabarito_por_destino():
    # As duas contagens que o relatório imprime lado a lado precisam ser
    # separáveis, senão o leitor compara lançamentos órfãos com casos.
    pares = generate_clean_pairs(seed=9, n=4)
    agregado = PagamentoAgregado().apply_many(Random(0), pares[:3])
    defasado = DefasagemTemporal().apply(Random(0), pares[3])
    ds = build_dataset(pares, injections=[agregado, defasado])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.truth_deterministic == 1
    assert m.truth_for_agent == 1


class _InvestigadorQueAcerta:
    """Propõe sempre o tipo que o gabarito diz."""

    name = "acerta"
    cost_class = CostClass.AGENTE

    def __init__(self, truth):
        self._por_id = {}
        for gt in truth:
            for i in gt.bank_ids | gt.ledger_ids:
                self._por_id[i] = gt.divergence_type

    def investigate(self, divergences):
        propostas = []
        for d in divergences:
            ids = d.bank_ids | d.ledger_ids
            tipo = next((self._por_id[i] for i in ids if i in self._por_id), None)
            if tipo is None:
                propostas.append(Proposal.abstencao(d.id, "fora do gabarito"))
            else:
                propostas.append(
                    Proposal(
                        divergence_id=d.id,
                        tipo=tipo,
                        explicacao="acertou",
                        evidencia=["evidência"],
                        confianca=Confidence.ALTA,
                        acao_sugerida="conciliar",
                        cost=Cost(input_tokens=100, calls=1),
                    )
                )
        return InvestigationOutput(propostas, Cost(input_tokens=100 * len(propostas),
                                                   calls=len(propostas)))

    def resolve(self, work: WorkSet) -> ResolverOutput:
        saida = self.investigate(work.as_divergences())
        return ResolverOutput(proposals=saida.proposals, cost=saida.cost)

    def describe(self) -> ResolverDescription:
        return ResolverDescription(self.name, self.cost_class, "acerta contra o gabarito")


def test_conta_matches_por_camada():
    pares = generate_clean_pairs(seed=9, n=20)
    ds = build_dataset(pares, injections=[])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.matches_by_layer["L1"] == 20
    assert "L2" not in m.matches_by_layer or m.matches_by_layer["L2"] == 0


def test_sem_investigador_as_metricas_de_proposta_ficam_zeradas():
    pares = generate_clean_pairs(seed=9, n=10)
    ds = build_dataset(pares, injections=[])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.proposals_total == 0
    assert m.proposals_correct == 0
    assert m.agent_cost_microcents == 0


def test_precisao_das_propostas_contra_o_gabarito():
    pares = generate_clean_pairs(seed=9, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(
        ds.bank,
        ds.ledger,
        definition=_definicao([*default_resolvers(), _InvestigadorQueAcerta(ds.truth)]),
    )
    m = evaluate(ds, r)

    assert m.proposals_total == len(r.divergences)
    assert m.proposals_correct >= 1


def test_abstencao_nao_conta_como_acerto_nem_como_erro():
    pares = generate_clean_pairs(seed=9, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    class _SempreAbstem:
        name = "abstem"
        cost_class = CostClass.AGENTE

        def investigate(self, divergences):
            ps = [Proposal.abstencao(d.id, "não sei") for d in divergences]
            return InvestigationOutput(ps, Cost.zero())

        def resolve(self, work: WorkSet) -> ResolverOutput:
            saida = self.investigate(work.as_divergences())
            return ResolverOutput(proposals=saida.proposals, cost=saida.cost)

        def describe(self) -> ResolverDescription:
            return ResolverDescription(self.name, self.cost_class, "sempre abstém")

    m = evaluate(
        ds,
        reconcile(
            ds.bank, ds.ledger, definition=_definicao([*default_resolvers(), _SempreAbstem()])
        ),
    )

    assert m.proposals_abstained == m.proposals_total
    assert m.proposals_correct == 0


def test_custo_do_agente_aparece_em_microcents():
    pares = generate_clean_pairs(seed=9, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    r = reconcile(
        ds.bank,
        ds.ledger,
        definition=_definicao([*default_resolvers(), _InvestigadorQueAcerta(ds.truth)]),
    )
    m = evaluate(ds, r, model="claude-opus-5")

    assert m.agent_cost_microcents == sum(
        c.microcents("claude-opus-5") for c in r.cost_by_resolver.values()
    )


def test_render_mostra_camadas_e_propostas():
    pares = generate_clean_pairs(seed=9, n=20)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    saida = evaluate(
        ds,
        reconcile(
            ds.bank,
            ds.ledger,
            definition=_definicao([*default_resolvers(), _InvestigadorQueAcerta(ds.truth)]),
        ),
    ).render()

    assert "L1" in saida
    assert "Propostas" in saida


def test_custo_e_reportado_por_resolver_nao_so_no_total():
    # Um selo por resolver na tela precisa do custo DAQUELE resolver. Um
    # número só do sistema inteiro não responde "a camada L2 vale o que custa".
    dataset = build_benchmark(seed=1, n=100, taxa_divergencia=0.15)
    investigador = _investigador_falso()
    resultado = reconcile(dataset.bank, dataset.ledger, definition=_com_agente(investigador))

    m = evaluate(dataset, resultado, model="claude-opus-5")

    assert m.cost_by_resolver_microcents["L1"] == 0
    assert m.cost_by_resolver_microcents["investigador"] > 0
    assert m.agent_cost_microcents == sum(m.cost_by_resolver_microcents.values())


def test_resolver_que_nao_custou_nada_aparece_com_zero_e_nao_some():
    # Um resolver ausente do dicionário e um resolver de custo zero são
    # coisas diferentes na tela: um é "não rodou", o outro é "de graça".
    dataset = build_benchmark(seed=1, n=100, taxa_divergencia=0.15)
    resultado = reconcile(dataset.bank, dataset.ledger)

    m = evaluate(dataset, resultado)

    assert set(m.cost_by_resolver_microcents) == {"L1", "L2", "L3"}
    assert all(v == 0 for v in m.cost_by_resolver_microcents.values())
