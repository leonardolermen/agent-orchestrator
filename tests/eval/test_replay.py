import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost
from orchestrator.eval.replay import RecordingClient, ReplayClient


def _respostas():
    return [
        LLMResponse(
            text="",
            tool_calls=[ToolCall(id="t1", name="historico_fornecedor",
                                 arguments={"fornecedor": "ACME"})],
            cost=Cost(input_tokens=10, calls=1),
        ),
        LLMResponse(text='{"tipo":"ESTORNO"}', tool_calls=[],
                    cost=Cost(input_tokens=20, output_tokens=5, calls=1)),
    ]


def test_gravacao_devolve_o_que_o_interno_devolveu(tmp_path):
    destino = tmp_path / "sessao.jsonl"
    gravador = RecordingClient(FakeLLMClient(_respostas()), destino)

    primeira = gravador.complete(system="s", messages=[], tools=[])

    assert primeira.tool_calls[0].name == "historico_fornecedor"
    assert destino.exists()


def test_reprise_reproduz_a_gravacao_sem_cliente_interno(tmp_path):
    destino = tmp_path / "sessao.jsonl"
    gravador = RecordingClient(FakeLLMClient(_respostas()), destino)
    gravador.complete(system="s", messages=[], tools=[])
    gravador.complete(system="s", messages=[], tools=[])

    reprise = ReplayClient(destino)
    a = reprise.complete(system="s", messages=[], tools=[])
    b = reprise.complete(system="s", messages=[], tools=[])

    assert a.tool_calls[0].arguments == {"fornecedor": "ACME"}
    assert b.text == '{"tipo":"ESTORNO"}'
    assert b.cost.output_tokens == 5


def test_reprise_preserva_o_modelo_gravado(tmp_path):
    destino = tmp_path / "sessao.jsonl"
    RecordingClient(
        FakeLLMClient(_respostas()[:1], model="claude-sonnet-5"), destino
    ).complete(system="s", messages=[], tools=[])

    assert ReplayClient(destino).model == "claude-sonnet-5"


def test_reprise_estoura_quando_pedem_mais_do_que_foi_gravado(tmp_path):
    destino = tmp_path / "sessao.jsonl"
    RecordingClient(FakeLLMClient(_respostas()[:1]), destino).complete(
        system="s", messages=[], tools=[]
    )
    reprise = ReplayClient(destino)
    reprise.complete(system="s", messages=[], tools=[])

    with pytest.raises(AssertionError):
        reprise.complete(system="s", messages=[], tools=[])


def test_reprise_de_arquivo_inexistente_e_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReplayClient(tmp_path / "nao-existe.jsonl")
