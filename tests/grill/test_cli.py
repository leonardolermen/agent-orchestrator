import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost
from orchestrator.grill import cli as grill_cli
from orchestrator.grill.entrevistador import Entrevistador


def _chamada(ferramenta: str, **args) -> LLMResponse:
    return LLMResponse(
        text="", tool_calls=[ToolCall(id="t", name=ferramenta, arguments=args)], cost=Cost.zero()
    )


def _propor() -> LLMResponse:
    return _chamada(
        "propor_workflow",
        nome="Acme",
        justificativa="j",
        resolvers=[{"nome": "L1"}, {"nome": "L2", "parametros": {"max_cents": 10}}],
    )


@pytest.fixture(autouse=True)
def _raiz_isolada(tmp_path, monkeypatch):
    # Sem isto os testes escreveriam no `data/` real do desenvolvedor — o
    # mesmo defeito que `tests/conftest.py` já corrige para a fila.
    monkeypatch.setattr(grill_cli, "_RAIZ", tmp_path)


def _rodar(argv, respostas, entrevistador):
    it = iter(respostas)
    return grill_cli.main(argv, entrevistador=entrevistador, responder=lambda _: next(it))


def test_entrevista_feliz_grava_e_imprime_o_numero(capsys, tmp_path):
    ent = Entrevistador(client=FakeLLMClient([_chamada("perguntar", texto="p?"), _propor()]))

    codigo = _rodar(["--id", "acme", "--descricao", "conciliamos NF"], ["r"], ent)

    assert codigo == 0
    assert (tmp_path / "workflows" / "acme.json").exists()
    saida = capsys.readouterr().out
    assert "acme" in saida
    assert "%" in saida


def test_a_ressalva_aparece_sempre_que_ha_percentual(capsys):
    # Mostrar "87,1%" a um parceiro sem dizer sobre o que foi medido é vender
    # número que não é dele. A linha é requisito, não rodapé.
    ent = Entrevistador(client=FakeLLMClient([_propor()]))

    _rodar(["--id", "acme", "--descricao", "d"], [], ent)

    saida = capsys.readouterr().out
    assert "%" in saida
    assert grill_cli.RESSALVA in saida


def test_recusa_grava_e_sai_com_zero(capsys, tmp_path):
    ent = Entrevistador(
        client=FakeLLMClient(
            [_chamada("fora_do_catalogo", motivo="é cartão", o_que_faltaria="adquirente")]
        )
    )

    codigo = _rodar(["--id", "acme", "--descricao", "d"], [], ent)

    assert codigo == 0
    assert (tmp_path / "grill" / "recusas" / "acme.json").exists()
    assert not (tmp_path / "workflows" / "acme.json").exists()
    assert "adquirente" in capsys.readouterr().out


def test_entrevista_falha_nao_grava_e_imprime_a_transcricao(capsys, tmp_path):
    perguntas = [_chamada("perguntar", texto=f"p{i}") for i in range(2)]
    ent = Entrevistador(client=FakeLLMClient(perguntas), max_turnos=2)

    codigo = _rodar(["--id", "acme", "--descricao", "d"], ["a", "b"], ent)

    assert codigo == 1
    assert not (tmp_path / "workflows" / "acme.json").exists()
    assert "p0" in capsys.readouterr().out


def test_id_colidindo_recusa_antes_de_entrevistar(capsys, tmp_path):
    # Descobrir a colisão no fim desperdiçaria a conversa do parceiro.
    (tmp_path / "workflows").mkdir(parents=True)
    (tmp_path / "workflows" / "acme.json").write_text("{}", encoding="utf-8")
    cliente = FakeLLMClient([])

    codigo = _rodar(["--id", "acme", "--descricao", "d"], [], Entrevistador(client=cliente))

    assert codigo == 2
    assert cliente.chamadas == []
    assert "já existe" in capsys.readouterr().err


def test_exige_descricao():
    with pytest.raises(SystemExit):
        grill_cli.main(["--id", "acme"])


def test_descricao_por_arquivo(tmp_path, capsys):
    arquivo = tmp_path / "caso.md"
    arquivo.write_text("DESCRIÇÃO DO ARQUIVO", encoding="utf-8")
    cliente = FakeLLMClient([_propor()])

    _rodar(
        ["--id", "acme", "--descricao-arquivo", str(arquivo)], [], Entrevistador(client=cliente)
    )

    import json as _json

    mensagens = _json.dumps(cliente.chamadas[0]["messages"], ensure_ascii=False)
    assert "DESCRIÇÃO DO ARQUIVO" in mensagens
