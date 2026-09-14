from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.agent.proposal import Cost
from orchestrator.eval.agent_eval import EvalResult, avaliar


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
    # NOTA: o brief original pedia `assert r.model == "fake"` aqui. Essa
    # asserção é irreconciliável com `test_render_nomeia_o_modelo_e_a_precisao`
    # logo abaixo — as duas chamam `avaliar` do mesmo jeito (mesmo `model=`,
    # mesma `_fabrica_falsa`), mas uma exigia `self.model == "fake"` e a outra
    # exige `"claude-opus-5" in render()`, que só é possível se `self.model ==
    # "claude-opus-5"`. Nenhuma implementação de `avaliar`/`EvalResult`
    # satisfaz as duas ao mesmo tempo. O literal "fake" é resquício de uma
    # versão anterior de `FakeLLMClient` cujo modelo padrão era "fake" — ver o
    # comentário em `orchestrator/agent/llm.py` ("O modelo padrão é um de
    # verdade, não 'fake'"), que documenta exatamente essa mudança. Corrigido
    # para o valor que o restante do arquivo já pressupõe.
    assert r.model == "claude-opus-5"
    assert r.proposals_total > 0


def test_precisao_fica_entre_zero_e_um():
    r = avaliar(model="claude-opus-5", seed=1, n=40, taxa_divergencia=0.15,
                client_factory=_fabrica_falsa("claude-opus-5"))

    assert 0.0 <= r.precision <= 1.0


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
