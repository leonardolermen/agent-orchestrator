from types import SimpleNamespace

import pytest

from orchestrator.agent.anthropic_client import AnthropicClient


class _SDKFalso:
    """Duplo do SDK: registra o que recebeu e devolve o que foi preparado."""

    def __init__(self, resposta):
        self._resposta = resposta
        self.recebido = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.recebido = kwargs
        return self._resposta


def _resposta_sdk(blocos, uso):
    return SimpleNamespace(content=blocos, usage=uso)


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
