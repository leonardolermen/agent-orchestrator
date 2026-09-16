import re

import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.eval.replay import RecordingClient, ReplayClient
from orchestrator.kernel.cost import Cost


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


def test_gravador_recusa_sobrescrever_arquivo_existente_por_padrao(tmp_path):
    # Antes desta guarda, `RecordingClient.__init__` truncava o arquivo antes
    # da primeira chamada incondicionalmente — apontar um gravador para uma
    # gravação já existente destruía o histórico sem aviso.
    destino = tmp_path / "sessao.jsonl"
    destino.write_text("conteúdo pré-existente\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        RecordingClient(FakeLLMClient(_respostas()), destino)

    assert destino.read_text(encoding="utf-8") == "conteúdo pré-existente\n"


def test_gravador_sobrescreve_quando_pedido_explicitamente(tmp_path):
    destino = tmp_path / "sessao.jsonl"
    destino.write_text("conteúdo antigo\n", encoding="utf-8")

    gravador = RecordingClient(FakeLLMClient(_respostas()), destino, overwrite=True)
    gravador.complete(system="s", messages=[], tools=[])

    assert "conteúdo antigo" not in destino.read_text(encoding="utf-8")


def test_reprise_de_arquivo_vazio_e_erro_claro_nomeando_o_arquivo(tmp_path):
    destino = tmp_path / "vazio.jsonl"
    destino.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match=re.escape(str(destino))):
        ReplayClient(destino)


def test_reprise_de_arquivo_corrompido_e_erro_claro_nomeando_o_arquivo(tmp_path):
    destino = tmp_path / "corrompido.jsonl"
    destino.write_text("isto não é json\n", encoding="utf-8")

    with pytest.raises(ValueError, match=re.escape(str(destino))):
        ReplayClient(destino)
