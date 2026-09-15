from datetime import UTC, datetime

import pytest

from orchestrator.review.decision import Decision, Veredito, ids_de_conciliar_com
from orchestrator.taxonomy import DivergenceType


def test_parser_extrai_um_id():
    assert ids_de_conciliar_com("conciliar_com(l00003)") == frozenset({"l00003"})


def test_parser_extrai_varios_ids_separados_por_virgula():
    # O agente pode propor conciliar contra mais de uma contraparte — um
    # pagamento agregado é exatamente isso.
    assert ids_de_conciliar_com("conciliar_com(l1, l2 ,l3)") == frozenset(
        {"l1", "l2", "l3"}
    )


def test_parser_devolve_vazio_para_acao_que_nao_concilia():
    # `investigar_manual` e `ajustar` são ações válidas que NÃO conciliam.
    # Vazio aqui não é erro: aceitar uma proposta assim é concordar que ela
    # não casa nada.
    assert ids_de_conciliar_com("investigar_manual") == frozenset()
    assert ids_de_conciliar_com("ajustar(1500)") == frozenset()


def test_parser_devolve_vazio_para_forma_quebrada():
    assert ids_de_conciliar_com("conciliar_com(") == frozenset()
    assert ids_de_conciliar_com("conciliar_com()") == frozenset()
    assert ids_de_conciliar_com("") == frozenset()


def test_rejeitar_nao_carrega_tipo_nem_ids():
    d = Decision(
        divergence_id="d-1",
        veredito=Veredito.REJEITAR,
        tipo=None,
        conciliar_com=frozenset(),
        autor="controller@cliente",
        quando=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )

    assert d.tipo is None
    assert d.conciliar_com == frozenset()


def test_corrigir_exige_tipo():
    # Corrigir é aceitar com edição: sem o tipo que o humano afirma, não há
    # correção nenhuma, e a decisão não teria o que aplicar.
    with pytest.raises(ValueError, match="tipo"):
        Decision(
            divergence_id="d-1",
            veredito=Veredito.CORRIGIR,
            tipo=None,
            conciliar_com=frozenset({"l1"}),
            autor="controller@cliente",
            quando=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
        )


def test_quando_sem_fuso_e_rejeitado():
    # Um horário sem fuso não é um instante: comparar duas decisões de
    # máquinas diferentes daria ordem errada, e a trilha de auditoria depende
    # de ordem.
    with pytest.raises(ValueError, match="UTC"):
        Decision(
            divergence_id="d-1",
            veredito=Veredito.ACEITAR,
            tipo=DivergenceType.DEFASAGEM_TEMPORAL,
            conciliar_com=frozenset({"l1"}),
            autor="a",
            quando=datetime(2026, 9, 15, 12, 0),
        )
