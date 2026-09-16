from random import Random

from orchestrator.cli import build_benchmark
from orchestrator.conciliacao import default_resolvers, reconcile
from orchestrator.kernel.cost import Cost, CostClass
from orchestrator.kernel.definition import Stage, WorkflowDefinition
from orchestrator.kernel.resolution import Confidence, InvestigationOutput, Proposal, Resolution
from orchestrator.kernel.resolver import Resolver, ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkSet
from orchestrator.metrics import evaluate
from orchestrator.models import abstencao, banco, contabil, divergencias
from orchestrator.money import format_brl
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal, PagamentoAgregado


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
        divs = divergencias(work)
        return ResolverOutput(
            proposals=[abstencao(d.id, "teste") for d in divs],
            cost=Cost(input_tokens=100 * len(divs), calls=len(divs)),
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
                resolutions=[
                    Resolution(
                        item_ids=frozenset({f"id-fora-do-dataset-{i}" for i in range(10)})
                        | frozenset(
                            {f"outro-id-fora-do-dataset-{i}" for i in range(10)}
                        ),
                        produced_by=self.name,
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
            if not banco(work) or not contabil(work):
                return ResolverOutput()
            return ResolverOutput(
                resolutions=[
                    Resolution(
                        item_ids=frozenset({banco(work)[0].id})
                        | frozenset({contabil(work)[0].id}),
                        produced_by=self.name,
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
                propostas.append(abstencao(d.id, "fora do gabarito"))
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
        saida = self.investigate(divergencias(work))
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
            ps = [abstencao(d.id, "não sei") for d in divergences]
            return InvestigationOutput(ps, Cost.zero())

        def resolve(self, work: WorkSet) -> ResolverOutput:
            saida = self.investigate(divergencias(work))
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
    # coisas diferentes na tela: um é "não rodou", o outro é "de graça". Desde
    # que o revisor entrou na definição padrão (sempre presente, sempre a
    # custo zero) ele também roda aqui e aparece com 0 — é o mesmo caso do L1,
    # L2 e L3, não uma exceção.
    dataset = build_benchmark(seed=1, n=100, taxa_divergencia=0.15)
    resultado = reconcile(dataset.bank, dataset.ledger)

    m = evaluate(dataset, resultado)

    assert set(m.cost_by_resolver_microcents) == {"L1", "L2", "L3", "revisor"}
    assert all(v == 0 for v in m.cost_by_resolver_microcents.values())


class _ResolverHumanoFalso:
    """Casa o primeiro bancário com o primeiro contábil, como um humano faria."""

    name = "revisor"
    cost_class = CostClass.HUMANO

    def resolve(self, work):
        if not banco(work) or not contabil(work):
            return ResolverOutput()
        return ResolverOutput(
                resolutions=[
                Resolution(
                        item_ids=frozenset({banco(work)[0].id})
                        | frozenset({contabil(work)[0].id}),
                        produced_by="revisor",
                    rule="decisão humana",
                )
            ]
        )

    def describe(self):
        return ResolverDescription(self.name, self.cost_class, "humano falso")


def _com_humano():
    from orchestrator.conciliacao import default_resolvers
    from orchestrator.kernel.definition import Stage, WorkflowDefinition

    return WorkflowDefinition(
        id="com-humano",
        name="com humano",
        stages=(
            Stage("conciliar", (*default_resolvers(), _ResolverHumanoFalso())),
        ),
    )


def test_match_humano_nao_conta_como_falso_positivo():
    """O defeito que esta tarefa corrige.

    A regra de falso positivo conta QUALQUER toque num caso reservado ao
    agente. Escrita quando todo match era determinístico, ela estava certa.
    Com um humano na cascata ela se volta contra o produto: um controller
    aprovando o que o agente propôs seria registrado como erro.
    """
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)
    so_regras = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))
    com_humano = evaluate(
        dataset, reconcile(dataset.bank, dataset.ledger, definition=_com_humano())
    )

    assert com_humano.false_positives == so_regras.false_positives
    # A mesma separação por classe vale para falso negativo: um match humano
    # completando um caso parcialmente casado por regra mudaria esta contagem
    # se a separação REGRA-only fosse removida — mesmo raciocínio do brief,
    # agora com cobertura própria.
    assert com_humano.false_negatives == so_regras.false_negatives


def _so_humano():
    """Cascata com SÓ o revisor humano — nenhum resolver REGRA na definição.

    É o cenário que o Finding 1 da revisão descobriu: um stage só de revisão
    humana, sem nenhuma regra, é a forma óbvia que a cascata assume assim que
    o revisor humano for ligado antes de qualquer regra ou sem regra nenhuma.
    `matches_by_class` nunca ganha a chave REGRA nesse caso — não porque uma
    regra rodou e não casou nada, mas porque nenhuma rodou.
    """
    from orchestrator.kernel.definition import Stage, WorkflowDefinition

    return WorkflowDefinition(
        id="so-humano", name="só humano", stages=(Stage("revisar", (_ResolverHumanoFalso(),)),)
    )


def test_cascata_sem_regra_nenhuma_nao_finge_determinismo():
    """O fallback de `de_regra` precisa ser `[]`, não `result.matches`.

    Sem nenhum resolver REGRA na cascata, `matches_by_class` nunca cria a
    chave REGRA. Cair para `result.matches` nesse caso contaria a aprovação
    humana como determinística — o mesmo defeito desta tarefa, só que por uma
    porta diferente da que os outros testes cobrem.
    """
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)

    m = evaluate(dataset, reconcile(dataset.bank, dataset.ledger, definition=_so_humano()))

    assert m.false_positives == 0
    assert m.deterministic_rate == 0.0


def test_match_humano_nao_move_a_taxa_deterministica():
    # "Determinística" está no nome. Somar trabalho humano ali faria o número
    # que vende o produto — quanto as REGRAS resolvem — subir sem que nenhuma
    # regra tivesse melhorado.
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)
    so_regras = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))
    com_humano = evaluate(
        dataset, reconcile(dataset.bank, dataset.ledger, definition=_com_humano())
    )

    assert com_humano.deterministic_rate == so_regras.deterministic_rate
    assert com_humano.bank_matched == so_regras.bank_matched


def test_match_humano_sobe_a_taxa_de_resolucao_total():
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)
    so_regras = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))
    com_humano = evaluate(
        dataset, reconcile(dataset.bank, dataset.ledger, definition=_com_humano())
    )

    assert com_humano.bank_matched_total == so_regras.bank_matched_total + 1
    assert com_humano.resolution_rate > so_regras.resolution_rate


def test_dinheiro_conciliado_conta_o_trabalho_humano():
    # `divergent_amount` responde "quanto ainda está em aberto". Dinheiro que
    # um humano conciliou não está em aberto.
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)
    so_regras = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))
    com_humano = evaluate(
        dataset, reconcile(dataset.bank, dataset.ledger, definition=_com_humano())
    )

    assert com_humano.matched_amount > so_regras.matched_amount
    assert com_humano.divergent_amount < so_regras.divergent_amount
    # Direção sozinha passa para qualquer deslocamento não-nulo, incluindo um
    # errado (contar o lado contábil, contar em dobro, errar por N). Os dois
    # extratos bancários são o mesmo dataset, então a soma dos dois valores
    # tem que ser a mesma nos dois cenários — dinheiro só muda de coluna,
    # nunca de total.
    assert (
        com_humano.matched_amount + com_humano.divergent_amount
        == so_regras.matched_amount + so_regras.divergent_amount
    )


def test_so_regras_o_total_e_o_deterministico_coincidem():
    # Enquanto a cascata é só de regras, os dois números são o mesmo — é isso
    # que mantém o golden intacto.
    dataset = build_benchmark(seed=1, n=300, taxa_divergencia=0.15)

    m = evaluate(dataset, reconcile(dataset.bank, dataset.ledger))

    assert m.bank_matched_total == m.bank_matched
    assert m.resolution_rate == m.deterministic_rate
