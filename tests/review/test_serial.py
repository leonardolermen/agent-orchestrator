from datetime import UTC, datetime

from orchestrator.agent.proposal import Confidence, Proposal, TraceEvent, TraceKind
from orchestrator.kernel.cost import Cost
from orchestrator.review.decision import Decision, Veredito
from orchestrator.review.serial import (
    decisao_de_dict,
    decisao_para_dict,
    proposta_de_dict,
    proposta_para_dict,
)
from orchestrator.taxonomy import DivergenceType


def _proposta() -> Proposal:
    return Proposal(
        divergence_id="d-b-b00003",
        tipo=DivergenceType.DEFASAGEM_TEMPORAL,
        explicacao="liquidou 8 dias úteis depois",
        evidencia=["b00003: data 2026-08-26", "l00003: caixa 2026-08-15"],
        confianca=Confidence.ALTA,
        acao_sugerida="conciliar_com(l00003)",
        cost=Cost(input_tokens=11, output_tokens=22, cached_tokens=33,
                  cache_creation_tokens=44, calls=5),
        trace=[TraceEvent(kind=TraceKind.LLM, detail={"turnos": 6})],
    )


def test_proposta_sobrevive_a_ida_e_volta_inteira():
    # Os cinco campos de Cost e o trace precisam voltar. Uma serialização que
    # perde um campo em silêncio faz a fila reportar custo menor que o real e
    # uma auditoria perder o passo que explica a proposta.
    original = _proposta()

    voltou = proposta_de_dict(proposta_para_dict(original))

    assert voltou == original
    assert voltou.cost == original.cost
    assert voltou.trace[0].kind is TraceKind.LLM
    assert voltou.trace[0].detail == {"turnos": 6}


def test_decisao_sobrevive_a_ida_e_volta_inteira():
    original = Decision(
        divergence_id="d-b-b00003",
        veredito=Veredito.CORRIGIR,
        tipo=DivergenceType.RETENCAO_IMPOSTO,
        conciliar_com=frozenset({"l00003", "l00004"}),
        autor="controller@cliente",
        quando=datetime(2026, 9, 15, 12, 30, 45, tzinfo=UTC),
        motivo="é retenção de ISS, não defasagem",
    )

    voltou = decisao_de_dict(decisao_para_dict(original))

    assert voltou == original
    assert voltou.quando == original.quando
    assert voltou.conciliar_com == original.conciliar_com


def test_rejeitar_com_tipo_none_sobrevive():
    original = Decision(
        divergence_id="d-1", veredito=Veredito.REJEITAR, tipo=None,
        conciliar_com=frozenset(), autor="a",
        quando=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert decisao_de_dict(decisao_para_dict(original)).tipo is None


def test_ids_saem_ordenados_para_o_arquivo_ser_diffavel():
    d = Decision(
        divergence_id="d-1", veredito=Veredito.ACEITAR,
        tipo=DivergenceType.DEFASAGEM_TEMPORAL,
        conciliar_com=frozenset({"z", "a", "m"}), autor="a",
        quando=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert decisao_para_dict(d)["conciliar_com"] == ["a", "m", "z"]
