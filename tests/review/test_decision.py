from datetime import UTC, datetime

import pytest

from orchestrator.review.decision import Decision, Veredito, ids_de_conciliar_com
from orchestrator.taxonomy import DivergenceType


def test_parser_extrai_um_id():
    result = ids_de_conciliar_com("conciliar_com(l00003)")
    assert result == frozenset({"l00003"})
    assert isinstance(result, frozenset)


def test_parser_extrai_varios_ids_separados_por_virgula():
    # O agente pode propor conciliar contra mais de uma contraparte — um
    # pagamento agregado é exatamente isso.
    result = ids_de_conciliar_com("conciliar_com(l1, l2 ,l3)")
    assert result == frozenset({"l1", "l2", "l3"})
    assert isinstance(result, frozenset)


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


def test_parser_rejeita_ids_corrompidos_com_parenteses_extras():
    # Corrupção silenciosa é pior que rejeição honesta. Ids como 'l1)' ou
    # '(l1)' nunca casarão, mas parecem legítimos — é um sinal perdido de
    # que algo foi malformado no input.
    assert ids_de_conciliar_com("conciliar_com(l1))") == frozenset()
    assert ids_de_conciliar_com("conciliar_com((l1))") == frozenset()
    assert isinstance(ids_de_conciliar_com("conciliar_com((l1))"), frozenset)


def test_decision_e_hashavel():
    # Decision é @dataclass(frozen=True) e portanto deve ser hashável.
    # Um set em conciliar_com construiria sem erro mas quebraria ao hashear.
    d = Decision(
        divergence_id="d-1",
        veredito=Veredito.ACEITAR,
        tipo=DivergenceType.DEFASAGEM_TEMPORAL,
        conciliar_com=frozenset({"l1"}),
        autor="a",
        quando=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )
    # Não deve levantar TypeError
    hash(d)


def test_concilia_rejeitar_com_ids_nao_concilia():
    # REJEITAR nunca concilia, mesmo com ids preenchidos.
    d = Decision(
        divergence_id="d-1",
        veredito=Veredito.REJEITAR,
        tipo=None,
        conciliar_com=frozenset({"l1"}),
        autor="a",
        quando=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )
    assert d.concilia is False


def test_concilia_aceitar_sem_ids_nao_concilia():
    # ACEITAR com ids vazios não concilia — não há o que casar.
    d = Decision(
        divergence_id="d-1",
        veredito=Veredito.ACEITAR,
        tipo=DivergenceType.DEFASAGEM_TEMPORAL,
        conciliar_com=frozenset(),
        autor="a",
        quando=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
    )
    assert d.concilia is False
