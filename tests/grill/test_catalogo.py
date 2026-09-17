import pytest

from orchestrator.grill.catalogo import ClienteAusente
from orchestrator.kernel.cost import Cost


def test_cliente_ausente_tem_modelo_precificado():
    # `Agent.__post_init__`/`Investigator.__post_init__` chamam
    # `Cost.zero().microcents(client.model)`. Um nome inventado faria a
    # construção levantar — e um bloco AGENTE deixaria de ser sequer
    # DESENHÁVEL.
    Cost.zero().microcents(ClienteAusente().model)


def test_cliente_ausente_levanta_ao_ser_chamado():
    with pytest.raises(RuntimeError, match="ClienteAusente"):
        ClienteAusente().complete(system="s", messages=[], tools=[])


def test_o_entrevistador_oferece_blocos_de_TODAS_as_origens():
    """O defeito que esta fatia existe para fechar.

    `grill/catalogo.py` exportava `CATALOGO = ['L1','L2','L3','agente',
    'revisor']` — conciliação pura, sem noção de domínio. Descrever uma
    triagem de issues devolvia uma cascata bancária, e nem `api/entrevista.py`
    nem `Chat.tsx` mencionavam domínio em lugar nenhum.
    """
    from orchestrator.domains.registro import CATALOGO

    oferecidos = {r.nome for r in CATALOGO.regras} | {a.name for a in CATALOGO.agentes}

    assert "triador" in oferecidos, "o chat continua sem oferecer o agente de issues"
    assert "L1" in oferecidos, "o chat perdeu os blocos de conciliação"
    assert "revisor" in oferecidos, "o chat perdeu o degrau humano"
