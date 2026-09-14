import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost


def test_fake_devolve_as_respostas_na_ordem():
    a = LLMResponse(text="primeira", tool_calls=[], cost=Cost(calls=1))
    b = LLMResponse(text="segunda", tool_calls=[], cost=Cost(calls=1))
    cliente = FakeLLMClient([a, b])

    assert cliente.complete(system="s", messages=[], tools=[]).text == "primeira"
    assert cliente.complete(system="s", messages=[], tools=[]).text == "segunda"


def test_fake_registra_o_que_recebeu():
    cliente = FakeLLMClient([LLMResponse(text="ok", tool_calls=[], cost=Cost.zero())])
    cliente.complete(system="instrução", messages=[{"role": "user", "content": "oi"}], tools=[])

    assert cliente.chamadas[0]["system"] == "instrução"
    assert cliente.chamadas[0]["messages"][0]["content"] == "oi"


def test_fake_estoura_quando_acabam_as_respostas():
    # Um laço que pede mais respostas do que o teste preparou é laço descontrolado,
    # e o teste precisa gritar em vez de devolver None.
    cliente = FakeLLMClient([LLMResponse(text="única", tool_calls=[], cost=Cost.zero())])
    cliente.complete(system="s", messages=[], tools=[])

    with pytest.raises(AssertionError):
        cliente.complete(system="s", messages=[], tools=[])


def test_fake_pode_simular_chamada_de_ferramenta():
    r = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t1", name="buscar_lancamentos", arguments={"valor": 1000})],
        cost=Cost(calls=1),
    )
    cliente = FakeLLMClient([r])
    resposta = cliente.complete(system="s", messages=[], tools=[])

    assert resposta.tool_calls[0].name == "buscar_lancamentos"
    assert resposta.tool_calls[0].arguments["valor"] == 1000


def test_resposta_sem_texto_e_sem_ferramenta_e_invalida():
    with pytest.raises(ValueError):
        LLMResponse(text="", tool_calls=[], cost=Cost.zero())
