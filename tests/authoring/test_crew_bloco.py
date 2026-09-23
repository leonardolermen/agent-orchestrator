"""Uma tripulação componível: `Crew` existia inteiro e não tinha como ser montada.

O que estes testes fixam não é o `Crew` — ele tem os seus, 24 deles. É a
ENCANAÇÃO: que a declaração vira tripulação, que `abstem_com` sai dos agentes em
vez de ser perguntado outra vez, e que as recusas do `Crew` chegam a quem está na
tela com o nome do bloco na frente.
"""

from datetime import UTC, datetime

import pytest

from orchestrator.agent.declarado import AgenteDeclarado
from orchestrator.agent.llm import FakeLLMClient
from orchestrator.authoring.composicao import (
    BlocoCrew,
    Composicao,
    construir_composicao,
    de_json,
    para_json,
)

AGORA = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _agente(nome: str, abstem: str = "NAO_SEI") -> AgenteDeclarado:
    return AgenteDeclarado(
        name=nome,
        system="classifique",
        kind="chamado",
        prompt="{assunto}",
        tipos=("INCIDENTE", "SOLICITACAO"),
        abstem_com=abstem,
    )


def _bloco(**kw) -> BlocoCrew:
    base = dict(nome="time", agentes=(_agente("ana"), _agente("bruno")))
    return BlocoCrew(**{**base, **kw})


def _compor(bloco: BlocoCrew):
    c = Composicao(id="w", nome="W", gerado_em=AGORA, blocos=(bloco,))
    return construir_composicao(c, cliente_para=lambda _model: FakeLLMClient([]))


def test_a_declaracao_vira_tripulacao():
    d = _compor(_bloco())

    crew = d.stages[0].cascade[0]
    assert crew.name == "time"
    assert [a.name for a in crew.agents] == ["ana", "bruno"]


def test_abstem_com_sai_dos_AGENTES_e_nao_e_perguntado_de_novo():
    """Cada `AgenteDeclarado` já diz qual valor de `Proposal.tipo` significa
    "não sei". Perguntar outra vez criaria a segunda fonte de verdade, e o
    sintoma seria o Crew chamando de DESACORDO duas abstenções — que é
    exatamente o caso em que ele deveria se calar."""
    d = _compor(_bloco(agentes=(_agente("ana", "NAO_SEI"), _agente("bruno", "SEM_IDEIA"))))

    assert d.stages[0].cascade[0].abstem_com == frozenset({"NAO_SEI", "SEM_IDEIA"})


def test_a_tripulacao_DECLARA_o_que_consome():
    """Vazio significa "vejo o pool inteiro", e composto isso faria o degrau
    inteiro ver tudo: item de outro ramo entraria na tripulação e sairia com
    proposta de um agente que não fala sobre ele — caro e errado, sem erro."""
    d = _compor(_bloco())

    assert d.stages[0].consome == frozenset({"chamado"})


def test_a_recusa_do_CREW_chega_com_o_nome_do_bloco():
    """A mensagem do `Crew` fala do resolver; quem está na tela procura o bloco
    que montou. As duas informações juntas, uma vez só."""
    with pytest.raises(ValueError, match="tripulação 'time'"):
        _compor(_bloco(agentes=(_agente("ana"),)))


def test_conflito_por_MAIORIA_com_dois_agentes_e_recusado():
    # Com dois não há maioria — há empate, e empate por maioria é abstenção com
    # passos extras. Quem recusa é o `Crew`; aqui só se prova que a recusa
    # ATRAVESSA a composição em vez de virar uma tripulação que se cala sempre.
    with pytest.raises(ValueError, match="maioria"):
        _compor(_bloco(conflito="maioria"))


def test_hierarquica_sem_gerente_e_recusada():
    with pytest.raises(ValueError, match="manager|gerente"):
        _compor(_bloco(process="hierarchical"))


def test_a_tripulacao_custa_CREW_e_roda_depois_do_agente_sozinho():
    """A classe de custo é o que ordena a cascata. Um Crew barato demais rodaria
    antes de um agente sozinho, que é mais barato de verdade."""
    from orchestrator.kernel.cost import CostClass

    d = _compor(_bloco())

    assert d.stages[0].cascade[0].cost_class is CostClass.CREW
    assert CostClass.AGENTE < CostClass.CREW


def test_ida_e_volta_pelo_disco():
    c = Composicao(id="w", nome="W", gerado_em=AGORA, blocos=(_bloco(conflito="abster"),))

    voltou = de_json(para_json(c))

    bloco = voltou.blocos[0]
    assert isinstance(bloco, BlocoCrew)
    assert [a.name for a in bloco.agentes] == ["ana", "bruno"]
    assert voltou.version == c.version


def test_o_nome_da_tripulacao_entra_na_unicidade_dos_blocos():
    """Mesma razão de sempre: `Run.resolved_by_resolver` é indexado por nome, e
    dois resolvers homônimos fundiriam as contagens."""
    c = Composicao(
        id="w", nome="W", gerado_em=AGORA, blocos=(_bloco(), _bloco())
    )

    with pytest.raises(ValueError, match="repetido"):
        construir_composicao(c, cliente_para=lambda _model: FakeLLMClient([]))
