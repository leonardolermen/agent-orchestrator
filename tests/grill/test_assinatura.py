import pytest

from orchestrator.agent.proposal import Cost


def test_o_cliente_de_assinatura_satisfaz_o_protocolo():
    # O entrevistador só conhece `LLMClient`. Esta é a única amarra.
    sdk = pytest.importorskip("claude_agent_sdk")  # noqa: F841
    from orchestrator.grill.assinatura import ClienteAssinatura

    cliente = ClienteAssinatura()
    assert hasattr(cliente, "model")
    assert callable(cliente.complete)


def test_o_modelo_do_cliente_e_precificado():
    # Mesma razão do `ClienteAusente`: um nome fora da tabela de preços faria
    # todo cálculo de orçamento levantar.
    pytest.importorskip("claude_agent_sdk")
    from orchestrator.grill.assinatura import ClienteAssinatura

    Cost.zero().microcents(ClienteAssinatura().model)


def test_o_entrevistador_nao_importa_o_sdk():
    # A prova de que o adaptador é substituível: o laço inteiro roda sem o
    # extra instalado.
    import orchestrator.grill.entrevistador as ent

    fonte = (ent.__file__).replace(".pyc", ".py")
    with open(fonte, encoding="utf-8") as f:
        assert "claude_agent_sdk" not in f.read()
