import inspect
import pathlib

from orchestrator.kernel.cost import Cost


def test_o_cliente_de_assinatura_satisfaz_o_protocolo():
    # O entrevistador só conhece `LLMClient`. Esta é a única amarra. `hasattr`
    # sozinho passaria para qualquer objeto com dois atributos de nome certo
    # — inclusive um `complete` de assinatura incompatível, que é exatamente
    # a falha que este teste existe para pegar. Por isso a FORMA dos
    # parâmetros é travada, não só a presença do método.
    from orchestrator.grill.assinatura import ClienteAssinatura

    cliente = ClienteAssinatura()
    assert hasattr(cliente, "model")
    assert callable(cliente.complete)
    assert list(inspect.signature(cliente.complete).parameters) == [
        "system",
        "messages",
        "tools",
    ]


def test_o_modelo_do_cliente_e_precificado():
    # Mesma razão do `ClienteAusente`: um nome fora da tabela de preços faria
    # todo cálculo de orçamento levantar.
    from orchestrator.grill.assinatura import ClienteAssinatura

    Cost.zero().microcents(ClienteAssinatura().model)


def test_o_entrevistador_nao_importa_o_sdk():
    # A prova de que o adaptador é substituível: o laço inteiro roda sem o
    # extra instalado. Varre o PACOTE inteiro do grill, não só
    # `entrevistador.py` — um `import claude_agent_sdk` escondido em
    # `cli.py` ou `registro.py`, por exemplo, passaria batido com um teste
    # de arquivo único. `assinatura.py` é a única exceção prevista: é o
    # adaptador que documenta a sonda do SDK em comentário, sem importá-lo
    # de fato (a implementação escolhida é um alias de `AnthropicClient`).
    raiz = pathlib.Path(__file__).resolve().parents[2] / "src" / "orchestrator" / "grill"
    for arquivo in raiz.glob("*.py"):
        if arquivo.name == "assinatura.py":
            continue
        texto = arquivo.read_text(encoding="utf-8")
        assert "claude_agent_sdk" not in texto, f"{arquivo.name} vazou o SDK"
