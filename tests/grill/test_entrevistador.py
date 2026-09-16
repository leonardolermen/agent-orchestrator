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


def _chamada(ferramenta: str, cost: Cost | None = None, **args) -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=[ToolCall(id="t", name=ferramenta, arguments=args)],
        cost=cost if cost is not None else Cost.zero(),
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
        _chamada(
            "perguntar",
            texto="data de caixa ou competência?",
            cost=Cost(input_tokens=100, output_tokens=40, calls=1),
        ),
        _propor(cost=Cost(input_tokens=200, output_tokens=80, calls=1)),
    ])
    responder = _Respostas("caixa")

    r = Entrevistador(client=cliente).entrevistar("acme", "conciliamos NF com extrato", responder)

    assert isinstance(r, Proposta)
    assert r.receita.id == "acme"
    assert r.receita.nome == "Conciliação Acme"
    assert [x.nome for x in r.receita.resolvers] == ["L1", "L2"]
    assert r.receita.resolvers[1].parametros == {"max_cents": 10}
    assert responder.perguntas == ["data de caixa ou competência?"]
    # Custo é a métrica central do produto: precisa somar os DOIS turnos, não
    # só o último. Pina a mutação `cost=total -> cost=Cost.zero()`.
    assert r.cost == Cost(input_tokens=300, output_tokens=120, calls=2)


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
    # Pina o teto pelo NÚMERO DE CHAMADAS, não só pela mensagem de erro: uma
    # mutação que trocasse `range(max_turnos)` por `range(max_turnos - 1)`
    # ainda produziria "esgotou 3 turnos" e passaria pelas duas asserções
    # acima sem pegar o desvio de um turno a menos.
    assert len(cliente.chamadas) == 3


def test_recusa_e_desfecho_legitimo():
    cliente = FakeLLMClient([
        _chamada(
            "fora_do_catalogo",
            motivo="é cartão",
            o_que_faltaria="resolver de adquirente",
            cost=Cost(input_tokens=50, output_tokens=20, calls=1),
        )
    ])

    r = Entrevistador(client=cliente).entrevistar("acme", "concilio cartão", _Respostas())

    assert isinstance(r, RecusaFinal)
    assert r.motivo == "é cartão"
    assert r.o_que_faltaria == "resolver de adquirente"
    # Espelha a mesma pinagem de custo do teste feliz, no OUTRO ponto de
    # retorno: a mutação `cost=total -> cost=Cost.zero()` tocava os dois.
    assert r.cost == Cost(input_tokens=50, output_tokens=20, calls=1)


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


def test_chamada_paralela_de_ferramenta_nao_deixa_tool_use_orfao():
    # Espelha test_investigator.py::
    # test_multiplas_chamadas_de_ferramenta_voltam_em_uma_unica_mensagem.
    # O protocolo do grill não suporta ferramentas em paralelo — só a
    # PRIMEIRA (`tool_calls[0]`) é de fato honrada — mas o modelo pode pedir
    # mais de uma no mesmo turno, e cada `tool_use` gera um bloco. Se a
    # segunda ficar sem `tool_result`, a Messages API recusa a PRÓXIMA
    # chamada com 400: ela exige exatamente um `tool_result` por `tool_use`
    # do turno anterior. `FakeLLMClient` não valida forma de mensagem, então
    # só uma sonda como esta pega isso.
    cliente = FakeLLMClient([
        LLMResponse(
            text="",
            tool_calls=[
                ToolCall(id="tA", name="perguntar", arguments={"texto": "p1"}),
                ToolCall(id="tB", name="perguntar", arguments={"texto": "p2"}),
            ],
            cost=Cost.zero(),
        ),
        _propor(),
    ])

    r = Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas("resposta"))

    assert isinstance(r, Proposta)
    segunda_chamada = cliente.chamadas[1]["messages"]
    mensagens_de_resultado = [
        m for m in segunda_chamada if m["role"] == "user" and isinstance(m["content"], list)
    ]
    assert len(mensagens_de_resultado) == 1
    assert len(mensagens_de_resultado[0]["content"]) == 2
    ids = {b["tool_use_id"] for b in mensagens_de_resultado[0]["content"]}
    assert ids == {"tA", "tB"}
    orfao = next(b for b in mensagens_de_resultado[0]["content"] if b["tool_use_id"] == "tB")
    assert orfao["is_error"] is True


def test_falha_ao_consultar_o_modelo_vira_entrevista_falhou_com_transcricao():
    # Timeout, rede caída, 500 da API: a conversa do parceiro não pode se
    # perder atrás de uma exceção crua escapando do laço.
    class _ClienteQuebrado:
        model = "claude-opus-5"

        def complete(self, system, messages, tools):
            raise TimeoutError("rede caiu")

    with pytest.raises(EntrevistaFalhou, match="falha ao consultar o modelo") as erro:
        Entrevistador(client=_ClienteQuebrado()).entrevistar(
            "acme", "minha descrição", _Respostas()
        )

    assert any("minha descrição" in linha for linha in erro.value.transcricao)


def test_falha_ao_obter_resposta_do_parceiro_vira_entrevista_falhou():
    # Um EOFError de stdin fechado no meio da entrevista não pode apagar a
    # conversa que já aconteceu.
    cliente = FakeLLMClient([_chamada("perguntar", texto="qual a tolerância?")])

    def responder_quebrado(pergunta: str) -> str:
        raise EOFError("stdin fechado")

    with pytest.raises(EntrevistaFalhou, match="falha ao obter resposta do parceiro") as erro:
        Entrevistador(client=cliente).entrevistar("acme", "d", responder_quebrado)

    assert any("qual a tolerância?" in linha for linha in erro.value.transcricao)


def test_resposta_vazia_do_parceiro_vira_marcador():
    # A Messages API recusa `tool_result` de conteúdo vazio. `ferramentas.
    # _texto` já aplica a mesma disciplina no sentido inverso (rejeita texto
    # vazio vindo do MODELO); aqui é o texto vindo do PARCEIRO.
    cliente = FakeLLMClient([_chamada("perguntar", texto="tolerância?"), _propor()])

    r = Entrevistador(client=cliente).entrevistar("acme", "d", _Respostas("   "))

    assert isinstance(r, Proposta)
    enviado = json.dumps(cliente.chamadas[1]["messages"], ensure_ascii=False)
    assert '"content": "   "' not in enviado
    assert "(sem resposta)" in enviado


def test_tentativas_de_formato_nao_acumulam_atraves_de_turno_bem_sucedido():
    # Bug corrigido: erros nos turnos 1 e 3, com uma pergunta respondida
    # normalmente entre eles, não são "2 vezes SEGUIDAS" — são 1 de cada
    # vez. Sem o reset, a contagem cumulativa (1+1=2) dispararia
    # `EntrevistaFalhou` no turno 3 mesmo com `max_tentativas_formato=1`,
    # apesar de nunca ter havido dois erros consecutivos.
    ruim = _propor(resolvers=[{"nome": "L9"}])
    cliente = FakeLLMClient([
        ruim,
        _chamada("perguntar", texto="p"),
        ruim,
        _propor(),
    ])

    r = Entrevistador(client=cliente, max_tentativas_formato=1).entrevistar(
        "acme", "d", _Respostas("resp")
    )

    assert isinstance(r, Proposta)


def test_max_turnos_invalido_falha_na_construcao():
    with pytest.raises(ValueError, match="max_turnos"):
        Entrevistador(client=FakeLLMClient([]), max_turnos=0)


def test_budget_negativo_falha_na_construcao():
    with pytest.raises(ValueError, match="budget_microcents"):
        Entrevistador(client=FakeLLMClient([]), budget_microcents=-1)


def test_modelo_sem_preco_falha_na_construcao():
    # Não é abstenção nem `EntrevistaFalhou`: é erro de configuração. Sem
    # esta guarda, ele só apareceria DEPOIS de uma chamada já paga, no meio
    # do laço, e a transcrição se perderia atrás de um `ValueError` cru.
    class _SemPreco:
        model = "modelo-inexistente"

        def complete(self, system, messages, tools):
            raise AssertionError("não deveria chegar aqui")

    with pytest.raises(ValueError, match="modelo sem preço"):
        Entrevistador(client=_SemPreco())
