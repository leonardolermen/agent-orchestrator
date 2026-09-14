import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.agent.proposal import Cost
from orchestrator.eval.agent_eval import EvalResult, avaliar

# Valores MEDIDOS com n=100 na semente 1. A amostra de n=40 foi descartada de
# propósito: ela dava 2 corretas de 2 arriscadas, e 2/2 é 1,0 tanto com a
# fórmula certa quanto com ela invertida — pinar contadores numa amostra que não
# distingue a fórmula é teatro.
#
# Com estes números, a fórmula invertida daria 12/6 = 2,0, fora de [0,1].
PRECISAO_ESPERADA = {"total": 12, "abstidas": 0, "corretas": 6}


def _fabrica_falsa(model: str):
    """Sempre devolve a mesma proposta, sem tocar em rede."""
    def fabrica():
        return FakeLLMClient(
            model=model,
            respostas=[
                LLMResponse(
                    text='{"tipo":"DEFASAGEM_TEMPORAL","explicacao":"atraso",'
                         '"evidencia":["b1"],"confianca":"MEDIA",'
                         '"acao_sugerida":"conciliar"}',
                    tool_calls=[],
                    cost=Cost(input_tokens=50, output_tokens=20, calls=1),
                )
            ]
            * 500
        )
    return fabrica


def test_avaliacao_devolve_resultado_completo():
    r = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert isinstance(r, EvalResult)
    # NOTA (mantida de rounds anteriores, precisão da razão confirmada pelo
    # revisor no round 1): o brief pede `assert r.model == "fake"` aqui. Isso é
    # irrealizável sob qualquer implementação que combine com o resto do
    # próprio brief — `avaliar` monta `EvalResult(model=model)` a partir do
    # PARÂMETRO `model`, nunca de `cliente.model`; `r.model` jamais poderia
    # ser "fake" com `model="claude-opus-5"` passado explicitamente. O
    # literal "fake" é resquício de uma versão anterior de `FakeLLMClient`,
    # cujo modelo padrão foi trocado para um nome real — ver o comentário em
    # `orchestrator/agent/llm.py`. Corrigido para o valor que a própria
    # `avaliar` sempre produz. Reportado ao coordenador nos rounds 0 e 1; o
    # brief regenerado no round 2 ainda cola o literal antigo.
    assert r.model == "claude-opus-5"
    assert r.proposals_total > 0


def test_precisao_pina_os_contadores_e_o_valor():
    # Uma asserção de faixa (0 <= x <= 1) é satisfeita por qualquer
    # implementação, inclusive uma com numerador e denominador trocados. Com os
    # três contadores brutos E o valor resultante fixos, trocar a fórmula
    # quebra o teste.
    #
    # Os números abaixo são MEDIDOS nesta semente, não escolhidos: rode
    # `avaliar` e copie o que sair. Se o benchmark mudar de forma, este teste
    # falha — e esse é exatamente o momento em que alguém deveria olhar para
    # ele.
    r = avaliar(model="claude-opus-5", seed=1, n=100, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    arriscadas = r.proposals_total - r.proposals_abstained
    assert r.proposals_total == PRECISAO_ESPERADA["total"]
    assert r.proposals_abstained == PRECISAO_ESPERADA["abstidas"]
    assert r.proposals_correct == PRECISAO_ESPERADA["corretas"]
    assert r.precision == PRECISAO_ESPERADA["corretas"] / arriscadas


def test_so_abstencoes_zera_a_precisao_sem_dividir_por_zero():
    # Sem este caso, o denominador `total - abstidas` nunca é exercido com
    # abstenções maiores que zero, e o ramo de denominador zero não é tocado
    # por teste nenhum. Medido: 12 propostas, todas abstenções.
    def fabrica():
        return FakeLLMClient(
            model="claude-opus-5",
            respostas=[
                LLMResponse(
                    text='{"tipo":"NAO_IDENTIFICADO","explicacao":"nao sei",'
                         '"evidencia":[],"confianca":"BAIXA",'
                         '"acao_sugerida":"investigar_manual"}',
                    tool_calls=[],
                    cost=Cost(input_tokens=50, output_tokens=20, calls=1),
                )
            ]
            * 500,
        )

    r = avaliar(model="claude-opus-5", seed=1, n=100, taxa_divergencia=0.15,
                client_factory=fabrica)

    assert r.proposals_abstained == r.proposals_total
    assert r.proposals_correct == 0
    assert r.precision == 0.0
    assert r.abstention_rate == 1.0


def test_fabrica_que_devolve_outro_modelo_e_rejeitada():
    # Pedir um modelo e medir outro produziria um relatório precificado numa
    # tabela e rotulado como outra.
    with pytest.raises(ValueError):
        avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-haiku-4-5"))


def test_custo_por_divergencia_e_inteiro_em_microcents():
    r = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert isinstance(r.microcents_per_divergence, int)


def test_avaliacao_e_deterministica_para_a_mesma_semente():
    a = avaliar(model="claude-opus-5", seed=5, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))
    b = avaliar(model="claude-opus-5", seed=5, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert a.precision == b.precision
    assert a.proposals_total == b.proposals_total


def test_render_nomeia_o_modelo_e_a_precisao():
    saida = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                    client_factory=_fabrica_falsa("claude-opus-5")).render()

    assert "claude-opus-5" in saida
    assert "Precisão" in saida
