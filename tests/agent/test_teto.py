"""O teto da execução, e o orçamento que vários clientes dividem.

Até aqui o teto só era exercitado pela BORDA (`tests/api/test_execucao.py`), o
que bastava enquanto havia um cliente por requisição. Com `model` por bloco há
vários, e o que precisa de teste próprio é o acumulador: um por cliente daria
um teto por modelo, e o pedido que autorizou gastar X gastaria X por modelo.
"""

import pytest

from orchestrator.agent.llm import FakeLLMClient, LLMResponse
from orchestrator.agent.teto import ClienteComTeto, Orcamento, TetoDaExecucaoEstourado
from orchestrator.kernel.cost import Cost


def _resposta(custo: Cost | None = None) -> LLMResponse:
    return LLMResponse(
        text="ok",
        tool_calls=[],
        cost=custo if custo is not None else Cost(input_tokens=100, output_tokens=20),
    )


def _cliente(model: str, *, orcamento=None, teto=None, custo=None) -> ClienteComTeto:
    interno = FakeLLMClient([_resposta(custo)], model=model)
    if orcamento is not None:
        return ClienteComTeto(interno, orcamento=orcamento)
    return ClienteComTeto(interno, teto_microcents=teto)


def test_dois_clientes_de_MODELOS_diferentes_dividem_um_teto():
    """O teto é da REQUISIÇÃO, não do modelo. Com um acumulador por cliente,
    uma cascata com dois modelos teria dois tetos que não somam — e o pedido
    que autorizou gastar X gastaria 2X sem ninguém pedir."""
    orcamento = Orcamento(teto_microcents=100_000_000)
    caro = _cliente("claude-opus-5", orcamento=orcamento)
    barato = _cliente("claude-haiku-4-5", orcamento=orcamento)

    caro.complete(system="s", messages=[], tools=[])
    barato.complete(system="s", messages=[], tools=[])

    # Um acumulador só: os dois embrulhos leem o MESMO número.
    assert orcamento.gasto_microcents() == caro.gasto_microcents()
    assert orcamento.gasto_microcents() == barato.gasto_microcents()


def test_o_gasto_de_cada_chamada_entra_no_PRECO_DO_SEU_MODELO():
    """100 tokens de entrada custam 500 µ¢ cada em opus e 100 em haiku, pela
    tabela. Acumular TOKENS e converter uma vez no fim daria o mesmo número
    para consumos que custam diferente — e é essa a conta que o produto vende.
    """
    so_opus = Orcamento()
    _cliente("claude-opus-5", orcamento=so_opus, custo=Cost(input_tokens=100)).complete(
        system="s", messages=[], tools=[]
    )

    so_haiku = Orcamento()
    _cliente("claude-haiku-4-5", orcamento=so_haiku, custo=Cost(input_tokens=100)).complete(
        system="s", messages=[], tools=[]
    )

    assert so_opus.gasto_microcents() == 100 * 500
    assert so_haiku.gasto_microcents() == 100 * 100


def test_a_RECUSA_e_contada_no_orcamento_compartilhado():
    """`api/app.py` lê as recusas para dizer `teto_atingido`, e a pergunta é
    sobre a REQUISIÇÃO — com dois clientes, a recusa pode cair em qualquer um
    deles."""
    orcamento = Orcamento(teto_microcents=1)
    a = _cliente("claude-opus-5", orcamento=orcamento)
    b = _cliente("claude-haiku-4-5", orcamento=orcamento)

    # A primeira PASSA: o teto é conferido antes da chamada, e nada tinha sido
    # gasto ainda. É a mesma forma documentada em `teto.py`.
    a.complete(system="s", messages=[], tools=[])
    with pytest.raises(TetoDaExecucaoEstourado):
        b.complete(system="s", messages=[], tools=[])

    assert orcamento.recusas == 1
    assert a.recusas == 1 and b.recusas == 1


def test_sem_orcamento_o_cliente_cria_o_seu_e_nada_muda():
    """`ClienteComTeto(fake, teto_microcents=X)` é o que todo chamador de hoje
    escreve, e continua significando um teto só para aquele cliente."""
    c = _cliente("claude-opus-5", teto=50)

    assert c.gasto_microcents() == 0
    assert c.recusas == 0
    assert c.teto_microcents == 50


def test_orcamento_E_teto_juntos_sao_recusados():
    """Dois valores para o mesmo teto seriam duas respostas para a mesma
    pergunta, e a que perdesse seria a que ninguém testa."""
    with pytest.raises(ValueError, match="OU"):
        ClienteComTeto(
            FakeLLMClient([], model="claude-opus-5"),
            teto_microcents=10,
            orcamento=Orcamento(20),
        )


def test_teto_NEGATIVO_e_recusado_na_construcao_do_orcamento():
    """Nasceria estourado e faria todo item abster sem nunca chamar o modelo —
    pareceria um agente com orçamento zerado, em vez de configuração inválida."""
    with pytest.raises(ValueError, match="negativo"):
        Orcamento(-1)
