import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.agent.proposal import Cost
from orchestrator.eval.agent_eval import EvalResult, avaliar

# Preenchido com os valores MEDIDOS na semente 1, n=40. Rode `avaliar` uma vez
# e copie a saída; não invente os números.
#
# Medido com:
#   avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
#           client_factory=_fabrica_falsa("claude-opus-5"))
# -> proposals_total=2, proposals_abstained=0, proposals_correct=2
PRECISAO_ESPERADA = {"total": 2, "abstidas": 0, "corretas": 2}


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
    # NOTA (mantida do round anterior, precisão confirmada pelo revisor): o
    # brief pede `assert r.model == "fake"` aqui. Isso é irrealizável sob
    # qualquer implementação que combine com o resto do próprio brief —
    # `avaliar` monta `EvalResult(model=model)` a partir do PARÂMETRO
    # `model`, nunca de `cliente.model`; `r.model` jamais poderia ser "fake"
    # com `model="claude-opus-5"` passado explicitamente. O literal "fake" é
    # resquício de uma versão anterior de `FakeLLMClient`, cujo modelo padrão
    # foi trocado para um nome real — ver o comentário em
    # `orchestrator/agent/llm.py`. Corrigido para o valor que a própria
    # `avaliar` sempre produz.
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
    r = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    arriscadas = r.proposals_total - r.proposals_abstained
    assert r.proposals_total == PRECISAO_ESPERADA["total"]
    assert r.proposals_abstained == PRECISAO_ESPERADA["abstidas"]
    assert r.proposals_correct == PRECISAO_ESPERADA["corretas"]
    assert r.precision == PRECISAO_ESPERADA["corretas"] / arriscadas


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
