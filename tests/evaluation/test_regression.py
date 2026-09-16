"""A detecção de regressão, e a razão pela qual ela reduz por mínimo.

A decisão 26 do repositório: *"um teste de regressão precisa pegar ALGUMA
semente colapsar, não a média deslizar; a média esconde exatamente o caso que
interessa."* Os dois primeiros testes aqui são a demonstração numérica disso —
o mesmo conjunto de sementes passa pela média e falha pelo mínimo.
"""

import pytest

from orchestrator.evaluation.metrics import EvalMetrics
from orchestrator.evaluation.regression import RegressionCheck


def m(
    precision=0.9,
    abstention=0.1,
    fp=0,
    fn=0,
    por_acerto=1_000_000,
    api_failures=0,
) -> EvalMetrics:
    return EvalMetrics(
        dataset_version="v",
        items_total=100,
        deterministic_rate=0.85,
        resolution_rate=0.9,
        false_positives=fp,
        false_negatives=fn,
        proposal_precision=precision,
        abstention_rate=abstention,
        microcents_total=10_000_000,
        microcents_per_item=100_000,
        microcents_per_correct_proposal=por_acerto,
        escalation_rate=0.05,
        api_failures=api_failures,
        proposals_total=15,
        proposals_correct=10,
        proposals_abstained=2,
    )


# -- a decisão 26, demonstrada ---------------------------------------------


def test_uma_semente_que_COLAPSA_e_pega_mesmo_com_a_media_alta():
    """Cinco sementes a 90% e uma a 20%: média 78%, mínimo 20%.

    Pela média, a queda é de 12 pontos e passa em qualquer limiar razoável.
    Pelo mínimo, é de 70 pontos. Este é o caso inteiro da decisão 26 num teste.
    """
    base = [m(precision=0.9)] * 6
    atual = [m(precision=0.9)] * 5 + [m(precision=0.2)]

    media_atual = sum(x.proposal_precision for x in atual) / len(atual)
    assert media_atual > 0.75  # a média sobreviveria

    relatorio = RegressionCheck().verificar(base, atual)

    assert not relatorio.passou
    assert any(v.regra == "max_precision_drop" for v in relatorio.violacoes)


def test_a_violacao_carrega_os_DOIS_numeros():
    """Uma mensagem de CI que só diz 'precisão caiu' custa um ciclo inteiro
    para descobrir quanto."""
    relatorio = RegressionCheck().verificar([m(precision=0.9)], [m(precision=0.2)])

    (v,) = [x for x in relatorio.violacoes if x.regra == "max_precision_drop"]
    assert v.base == 0.9 and v.atual == 0.2
    assert "0.9" in str(v) and "0.2" in str(v)


def test_queda_dentro_do_limiar_NAO_e_regressao():
    """Um modelo não determinístico varia entre execuções; um CI que dá alarme
    falso é um CI que as pessoas aprendem a ignorar."""
    assert RegressionCheck().verificar([m(precision=0.90)], [m(precision=0.87)]).passou


# -- tolerância zero --------------------------------------------------------


def test_UM_falso_positivo_em_UMA_semente_reprova():
    """O falso negativo custa um agente; o falso positivo fecha errado e
    ninguém olha (decisão 24). Só ele tem tolerância zero."""
    relatorio = RegressionCheck().verificar([m()] * 3, [m(), m(fp=1), m()])

    assert not relatorio.passou
    assert any("false_positives" in v.regra for v in relatorio.violacoes)


def test_falso_NEGATIVO_nao_tem_tolerancia_zero_por_padrao():
    assert RegressionCheck().verificar([m()] * 3, [m(), m(fn=4), m()]).passou


def test_tolerancia_zero_olha_a_PIOR_semente_e_nao_a_soma():
    relatorio = RegressionCheck().verificar([m()] * 2, [m(fp=1), m(fp=3)])

    (v,) = [x for x in relatorio.violacoes if "false_positives" in x.regra]
    assert v.atual == 3


def test_tolerancia_zero_sobre_campo_que_nao_e_contagem_e_recusada():
    """`proposal_precision` é uma TAXA; tolerância zero nela travaria o CI em
    qualquer variação de ponto flutuante."""
    with pytest.raises(ValueError, match="contagem de erro"):
        RegressionCheck(zero_tolerance=("proposal_precision",))


# -- a estratégia de não responder -----------------------------------------


def test_abster_de_TUDO_nao_passa_como_melhoria():
    """Sem esta regra, 'não responder nada' seria a estratégia ótima contra o
    CI: a precisão das que sobraram sobe, e nada mais é medido."""
    base = [m(precision=0.9, abstention=0.10)]
    atual = [m(precision=1.0, abstention=0.95)]

    relatorio = RegressionCheck().verificar(base, atual)

    assert not relatorio.passou
    assert any(v.regra == "max_abstention_increase" for v in relatorio.violacoes)


# -- custo ------------------------------------------------------------------


def test_custo_por_ACERTO_e_o_que_conta():
    """Um braço 30% mais caro que acerta o dobro não é regressão.

    `microcents_total` idêntico nos dois; o que muda é o custo por acerto, e é
    ele que a regra olha.
    """
    barato_e_ruim = [m(por_acerto=3_000_000)]
    caro_e_bom = [m(por_acerto=1_000_000)]

    assert RegressionCheck().verificar(barato_e_ruim, caro_e_bom).passou
    assert not RegressionCheck().verificar(caro_e_bom, barato_e_ruim).passou


def test_semente_sem_acerto_nenhum_reprova_em_vez_de_sumir():
    """`None` propaga: substituí-lo por zero faria o colapso total de uma
    semente MELHORAR a métrica agregada, que é o pior resultado possível."""
    relatorio = RegressionCheck().verificar([m()] * 2, [m(), m(por_acerto=None)])

    assert not relatorio.passou
    assert any(v.regra == "max_cost_increase" for v in relatorio.violacoes)


# -- as comparações que o módulo se recusa a fazer --------------------------


def test_numero_de_sementes_diferente_e_recusado():
    """Três contra dez mediria quantas sementes rodaram, não o código: a
    redução pessimista fica mais severa do lado com mais sementes."""
    with pytest.raises(ValueError, match="sementes diferentes"):
        RegressionCheck().verificar([m()] * 3, [m()] * 10)


def test_lista_vazia_e_recusada_em_vez_de_passar():
    """'Sem regressão' por ausência de dado é a mentira mais confortável que um
    CI pode contar."""
    with pytest.raises(ValueError, match="dos dois lados"):
        RegressionCheck().verificar([], [m()])
