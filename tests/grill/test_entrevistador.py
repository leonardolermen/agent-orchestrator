import json

import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse, ToolCall
from orchestrator.agent.proposal import Cost
from orchestrator.grill.entrevistador import (
    Entrevistador,
    EntrevistaFalhou,
    Proposta,
    RecusaFinal,
)


def _chamada(ferramenta: str, **args) -> LLMResponse:
    return LLMResponse(
        text="", tool_calls=[ToolCall(id="t", name=ferramenta, arguments=args)], cost=Cost.zero()
    )


def _propor(**extra):
    base = {
        "nome": "Conciliação Acme",
        "justificativa": "consolidam por fornecedor",
        "resolvers": [{"nome": "L1"}, {"nome": "L2", "parametros": {"max_cents": 10}}],
    }
    base.update(extra)
    return _chamada("propor_workflow", **base)


class _Respostas:
    """Substitui stdin: devolve respostas na ordem e registra as perguntas."""

    def __init__(self, *respostas: str) -> None:
        self.perguntas: list[str] = []
        self._respostas = list(respostas)

    def __call__(self, pergunta: str) -> str:
        self.perguntas.append(pergunta)
        assert self._respostas, (
            f"o modelo perguntou {len(self.perguntas)} vezes; o teste previu menos"
        )
        return self._respostas.pop(0)


def test_entrevista_feliz_produz_receita():
    cliente = FakeLLMClient([
        _chamada("perguntar", texto="data de caixa ou competência?"),
        _propor(),
    ])
    responder = _Respostas("caixa")

    r = Entrevistador(client=cliente).entrevistar("acme", "conciliamos NF com extrato", responder)

    assert isinstance(r, Proposta)
    assert r.receita.id == "acme"
    assert r.receita.nome == "Conciliação Acme"
    assert [x.nome for x in r.receita.resolvers] == ["L1", "L2"]
    assert r.receita.resolvers[1].parametros == {"max_cents": 10}
    assert responder.perguntas == ["data de caixa ou competência?"]


def test_a_descricao_entra_como_primeiro_turno_do_usuario():
    cliente = FakeLLMClient([_propor()])
    Entrevistador(client=cliente).entrevistar("acme", "MINHA DESCRIÇÃO", _Respostas())

    primeira = cliente.chamadas[0]["messages"][0]
    assert primeira["role"] == "user"
    assert "MINHA DESCRIÇÃO" in json.dumps(primeira, ensure_ascii=False)


def test_proposta_invalida_volta_ao_modelo_com_a_mensagem_do_resolver():
    # A asserção é sobre o que o modelo RECEBEU, não sobre o resultado final.
    # Asserção só no resultado passaria com um laço que ignorou o erro e deu
    # sorte no turno seguinte.
    cliente = FakeLLMClient([
        _propor(resolvers=[{"nome": "L2", "parametros": {"max_cents": -1}}]),
        _propor(),
    ])

    r = Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas())

    assert isinstance(r, Proposta)
    enviado = json.dumps(cliente.chamadas[1]["messages"], ensure_ascii=False)
    assert "max_cents não pode ser negativo" in enviado


def test_erro_de_ferramenta_desconhecida_tambem_volta_ao_modelo():
    cliente = FakeLLMClient([_chamada("pensar"), _propor()])

    r = Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas())

    assert isinstance(r, Proposta)
    enviado = json.dumps(cliente.chamadas[1]["messages"], ensure_ascii=False)
    assert "ferramenta desconhecida" in enviado


def test_tentativas_de_formato_esgotadas_falha_alto():
    ruim = _propor(resolvers=[{"nome": "L9"}])
    cliente = FakeLLMClient([ruim, ruim, ruim])

    with pytest.raises(EntrevistaFalhou, match="formato"):
        Entrevistador(client=cliente, max_tentativas_formato=2).entrevistar(
            "acme", "d", _Respostas()
        )


def test_turnos_esgotados_falha_alto_e_preserva_a_transcricao():
    # A conversa do parceiro não pode se perder por erro nosso.
    perguntas = [_chamada("perguntar", texto=f"p{i}") for i in range(3)]
    cliente = FakeLLMClient(perguntas)

    with pytest.raises(EntrevistaFalhou) as erro:
        Entrevistador(client=cliente, max_turnos=3).entrevistar(
            "acme", "d", _Respostas("a", "b", "c")
        )

    assert "turnos" in str(erro.value)
    assert any("p0" in linha for linha in erro.value.transcricao)


def test_recusa_e_desfecho_legitimo():
    cliente = FakeLLMClient([
        _chamada("fora_do_catalogo", motivo="é cartão", o_que_faltaria="resolver de adquirente")
    ])

    r = Entrevistador(client=cliente).entrevistar("acme", "concilio cartão", _Respostas())

    assert isinstance(r, RecusaFinal)
    assert r.motivo == "é cartão"
    assert r.o_que_faltaria == "resolver de adquirente"


def test_orcamento_estourado_falha_alto():
    caro = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t", name="perguntar", arguments={"texto": "p"})],
        cost=Cost(input_tokens=10_000_000, output_tokens=10_000_000, calls=1),
    )
    cliente = FakeLLMClient([caro, caro])

    with pytest.raises(EntrevistaFalhou, match="orçamento"):
        Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas("a", "b"))


def test_orcamento_padrao_cobre_uma_entrevista_realista():
    # Trava a derivação do Step 1: se o prompt ou os schemas crescerem, o
    # default precisa crescer junto ou este teste quebra sozinho.
    from orchestrator.grill.entrevistador import ORCAMENTO_PADRAO
    from orchestrator.grill.ferramentas import esquemas
    from orchestrator.grill.prompt import SYSTEM

    overhead = len(SYSTEM) + len(json.dumps(esquemas(), ensure_ascii=False))
    um_turno = Cost(input_tokens=overhead // 4, output_tokens=200, calls=1)
    assert ORCAMENTO_PADRAO >= um_turno.microcents("claude-opus-5") * 12


def test_a_transcricao_registra_perguntas_e_respostas():
    cliente = FakeLLMClient([_chamada("perguntar", texto="qual a folga?"), _propor()])

    r = Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas("uns 10 centavos"))

    juntas = "\n".join(r.transcricao)
    assert "qual a folga?" in juntas
    assert "uns 10 centavos" in juntas


def test_id_invalido_e_recusado_antes_do_primeiro_turno():
    # Descobrir isso no fim desperdiçaria a conversa inteira do parceiro.
    cliente = FakeLLMClient([])

    with pytest.raises(ValueError, match="id"):
        Entrevistador(client=cliente).entrevistar("Acme!", "d", _Respostas())

    assert cliente.chamadas == []
