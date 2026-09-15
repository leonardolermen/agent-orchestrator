from types import SimpleNamespace
from typing import Any

import pytest

from orchestrator.agent.anthropic_client import AnthropicClient


class _SDKFalso:
    """Duplo do SDK: registra o que recebeu em CADA chamada e devolve as
    respostas preparadas, em ordem — ou a mesma resposta sempre, se só uma
    foi passada (compatibilidade com testes de chamada única)."""

    def __init__(self, resposta):
        if isinstance(resposta, list):
            self._fila: list[Any] | None = list(resposta)
            self._unica = None
        else:
            self._fila = None
            self._unica = resposta
        self.chamadas: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.chamadas.append(kwargs)
        if self._fila is not None:
            return self._fila.pop(0)
        return self._unica

    @property
    def recebido(self):
        """A última chamada recebida — nome mantido para os testes de
        chamada única já existentes."""
        return self.chamadas[-1] if self.chamadas else None


def _resposta_sdk(blocos, uso, stop_reason="end_turn"):
    return SimpleNamespace(content=blocos, usage=uso, stop_reason=stop_reason)


def _uso(entrada=100, saida=50, cache=0, escrita=0):
    return SimpleNamespace(
        input_tokens=entrada,
        output_tokens=saida,
        cache_read_input_tokens=cache,
        cache_creation_input_tokens=escrita,
    )


def test_traduz_bloco_de_texto():
    sdk = _SDKFalso(_resposta_sdk([SimpleNamespace(type="text", text="oi")], _uso()))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[{"role": "user", "content": "x"}], tools=[])

    assert r.text == "oi"
    assert r.cost.input_tokens == 100
    assert r.cost.calls == 1


def test_traduz_bloco_de_ferramenta():
    bloco = SimpleNamespace(type="tool_use", id="t1", name="buscar_lancamentos",
                            input={"valor": 10})
    sdk = _SDKFalso(_resposta_sdk([bloco], _uso()))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[], tools=[])

    assert r.tool_calls[0].name == "buscar_lancamentos"
    assert r.tool_calls[0].arguments == {"valor": 10}


def test_contabiliza_tokens_de_cache_separado():
    sdk = _SDKFalso(_resposta_sdk([SimpleNamespace(type="text", text="oi")],
                                  _uso(entrada=10, cache=990)))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[], tools=[])

    assert r.cost.cached_tokens == 990
    assert r.cost.input_tokens == 10


def test_contabiliza_escrita_de_cache():
    sdk = _SDKFalso(_resposta_sdk([SimpleNamespace(type="text", text="oi")],
                                  _uso(entrada=10, escrita=2000)))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[], tools=[])

    assert r.cost.cache_creation_tokens == 2000


def test_marca_o_system_para_cache():
    # System e ferramentas são idênticos entre divergências. Numa execução com
    # 116 delas, cachear isso é a maior economia isolada do plano.
    sdk = _SDKFalso(_resposta_sdk([SimpleNamespace(type="text", text="oi")], _uso()))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    c.complete(system="instrução longa", messages=[], tools=[])

    assert sdk.recebido["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_usa_o_modelo_configurado():
    sdk = _SDKFalso(_resposta_sdk([SimpleNamespace(type="text", text="oi")], _uso()))
    c = AnthropicClient(model="claude-sonnet-5", sdk=sdk)

    c.complete(system="s", messages=[], tools=[])

    assert sdk.recebido["model"] == "claude-sonnet-5"


def test_rejeita_modelo_sem_preco_conhecido():
    # Sem preço não há custo, e sem custo o produto não tem métrica.
    with pytest.raises(ValueError):
        AnthropicClient(model="claude-inventado", sdk=_SDKFalso(None))


def test_traduz_texto_e_ferramenta_no_mesmo_turno():
    # O modelo pode "pensar em voz alta" num bloco de texto e pedir uma
    # ferramenta no mesmo turno — os dois precisam sobreviver à tradução.
    texto = SimpleNamespace(type="text", text="vou verificar o histórico")
    ferramenta = SimpleNamespace(
        type="tool_use", id="t1", name="buscar_lancamentos", input={"valor": 10}
    )
    sdk = _SDKFalso(_resposta_sdk([texto, ferramenta], _uso()))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[], tools=[])

    assert r.text == "vou verificar o histórico"
    assert r.tool_calls[0].name == "buscar_lancamentos"
    assert r.raw_content == [texto, ferramenta]


def test_raw_content_carrega_os_blocos_crus_na_ordem():
    # CRITICAL 2 (defeito 3): sem isto, blocos de thinking (opus-5 roda
    # thinking adaptativo por padrão) seriam descartados, e a API exige
    # recebê-los de volta inalterados no próximo turno.
    bloco = SimpleNamespace(type="text", text="oi")
    sdk = _SDKFalso(_resposta_sdk([bloco], _uso()))
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[], tools=[])

    assert r.raw_content == [bloco]


def test_traduz_stop_reason():
    # I8: truncamento, recusa e falha de API são três problemas diferentes
    # que ficam indistinguíveis sem este campo.
    sdk = _SDKFalso(
        _resposta_sdk([SimpleNamespace(type="text", text="oi")], _uso(), stop_reason="max_tokens")
    )
    c = AnthropicClient(model="claude-opus-5", sdk=sdk)

    r = c.complete(system="s", messages=[], tools=[])

    assert r.stop_reason == "max_tokens"


def test_cliente_real_configura_timeout_e_tentativas(monkeypatch):
    # I7: o spec pede 3 tentativas (1 chamada + 2 retries). Deixar isso no
    # default (não configurado) do SDK faria o número morar num comentário
    # sobre o comportamento de OUTRA biblioteca, sujeito a mudar de versão
    # para versão sem que nada aqui avise.
    import anthropic

    capturado: dict[str, Any] = {}

    class _AnthropicFalso:
        def __init__(self, **kwargs):
            capturado.update(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", _AnthropicFalso)

    c = AnthropicClient(model="claude-opus-5")
    c._cliente()

    assert capturado["max_retries"] == 2
    assert capturado["timeout"] > 0


def test_laco_investigador_fala_o_protocolo_de_ferramentas_do_sdk():
    """CRITICAL 2: depois de uma ida-e-volta de ferramenta, a mensagem do
    assistente carrega os blocos tool_use ORIGINAIS (verbatim) e a mensagem
    de usuário seguinte é uma LISTA de blocos tool_result, cada um casado
    pelo `tool_use_id` da chamada que responde.

    `FakeLLMClient` e `ReplayClient` nunca pegariam esta classe de defeito —
    os dois ignoram `messages` completamente (ver seus docstrings). Este é o
    único arquivo do projeto que conhece o SDK, e por isso o único lugar que
    pode checar a forma da mensagem de saída contra o dublê do SDK.
    """
    from orchestrator.agent.investigator import Investigator
    from orchestrator.agent.tools import ToolContext
    from orchestrator.models import Divergence
    from orchestrator.synth.generator import build_dataset, generate_clean_pairs

    bloco_ferramenta = SimpleNamespace(
        type="tool_use",
        id="toolu_1",
        name="historico_fornecedor",
        input={"fornecedor": "ACME"},
    )
    resposta_1 = _resposta_sdk([bloco_ferramenta], _uso(), stop_reason="tool_use")
    resposta_2 = _resposta_sdk(
        [
            SimpleNamespace(
                type="text",
                text='{"tipo":"NAO_IDENTIFICADO","explicacao":"x","evidencia":[],'
                '"confianca":"BAIXA","acao_sugerida":"investigar_manual"}',
            )
        ],
        _uso(),
    )
    sdk = _SDKFalso([resposta_1, resposta_2])
    cliente = AnthropicClient(model="claude-opus-5", sdk=sdk)
    ds = build_dataset(generate_clean_pairs(seed=3, n=5), injections=[])
    ctx = ToolContext(bank=ds.bank, ledger=ds.ledger)
    inv = Investigator(client=cliente, context=ctx)

    divergencia = Divergence(
        id="d1", bank_ids=frozenset({ds.bank[0].id}), ledger_ids=frozenset()
    )
    inv.investigate([divergencia])

    assert len(sdk.chamadas) == 2
    segunda_chamada = sdk.chamadas[1]["messages"]
    assistente, resultado = segunda_chamada[-2], segunda_chamada[-1]

    assert assistente["role"] == "assistant"
    assert assistente["content"] == [bloco_ferramenta]  # verbatim, não reconstruído

    assert resultado["role"] == "user"
    assert isinstance(resultado["content"], list)
    assert resultado["content"][0]["type"] == "tool_result"
    assert resultado["content"][0]["tool_use_id"] == "toolu_1"
    assert "content" in resultado["content"][0]
