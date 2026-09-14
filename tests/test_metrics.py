from random import Random

from orchestrator.matching.engine import reconcile
from orchestrator.metrics import evaluate
from orchestrator.models import MatchResult
from orchestrator.money import format_brl
from orchestrator.synth.generator import build_dataset, generate_clean_pairs
from orchestrator.synth.injectors import DefasagemTemporal, PagamentoAgregado


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

    r = reconcile(ds.bank, ds.ledger, matchers=[ToleranceMatcher(max_business_days=999)])
    m = evaluate(ds, r)

    assert m.false_positives == 1


def test_taxa_fica_entre_zero_e_um():
    # Matcher hostil: devolve ids que não existem no dataset. `matchers` é um
    # ponto de extensão anunciado (reconcile aceita qualquer lista), então um
    # matcher com bug ou malicioso é um cenário alcançável, não hipotético.
    # Sem interseção com o dataset real, cada "casamento" fantasma infla o
    # numerador sem tocar o denominador — a taxa passa de 1.0 sem limite.
    class MatcherHostil:
        layer = "HOSTIL"

        def match(self, bank, ledger):
            # Mais ids fantasma que lançamentos reais no dataset: se o código
            # não intersectar com o dataset, o numerador ultrapassa o
            # denominador e a taxa passa de 1.0.
            return [
                MatchResult(
                    bank_ids=frozenset({f"id-fora-do-dataset-{i}" for i in range(10)}),
                    ledger_ids=frozenset({f"outro-id-fora-do-dataset-{i}" for i in range(10)}),
                    layer=self.layer,
                    rule="finge casar ids que não existem no dataset",
                    evidence={},
                )
            ]

    pares = generate_clean_pairs(seed=9, n=2)
    ds = build_dataset(pares, injections=[])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger, matchers=[MatcherHostil()]))

    assert 0.0 <= m.deterministic_rate <= 1.0


def test_cobertura_por_tipo_lista_os_tipos_injetados():
    pares = generate_clean_pairs(seed=9, n=10)
    inj = DefasagemTemporal().apply(Random(0), pares[0])
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.truth_by_type["DEFASAGEM_TEMPORAL"] == 1


def test_agregado_resolvido_por_l3_nao_e_falso_positivo():
    from orchestrator.synth.injectors import PagamentoAgregado

    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger))

    assert m.false_positives == 0
    assert m.false_negatives == 0


def test_falso_negativo_quando_camada_nao_resolve_o_que_deveria():
    from orchestrator.synth.injectors import PagamentoAgregado

    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    # sem nenhuma camada, o agregado deixa de ser resolvido
    m = evaluate(ds, reconcile(ds.bank, ds.ledger, matchers=[]))

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
    class MatcherParcial:
        layer = "PARCIAL"

        def match(self, bank, ledger):
            if not bank or not ledger:
                return []
            return [
                MatchResult(
                    bank_ids=frozenset({bank[0].id}),
                    ledger_ids=frozenset({ledger[0].id}),
                    layer=self.layer,
                    rule="casa só um dos contábeis, de propósito",
                    evidence={},
                )
            ]

    pares = generate_clean_pairs(seed=9, n=3)
    inj = PagamentoAgregado().apply_many(Random(0), pares)
    ds = build_dataset(pares, injections=[inj])

    m = evaluate(ds, reconcile(ds.bank, ds.ledger, matchers=[MatcherParcial()]))

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
