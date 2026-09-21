from datetime import UTC, datetime

from orchestrator.domains.reconciliation.taxonomy import DivergenceType
from orchestrator.kernel.cost import Cost
from orchestrator.kernel.resolution import Confidence, Proposal, TraceEvent, TraceKind
from orchestrator.review.decision import Decision, Veredito
from orchestrator.review.serial import (
    decisao_de_dict,
    decisao_para_dict,
    proposta_de_dict,
    proposta_para_dict,
)


def _proposta() -> Proposal:
    return Proposal(
        item_id="d-b-b00003",
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


def test_ida_e_volta_preserva_o_tipo_sem_conhecer_a_taxonomia():
    """A invariante de P2.6, agora garantida por IGUALDADE e não por coerção.

    Este teste já exigiu o contrário: que `proposta_de_dict` coagisse o `tipo`
    a `DivergenceType`, porque todo o projeto comparava por identidade
    (`p.tipo is DivergenceType.X`) e um `str` cru não casava com nada — a
    precisão do agente era contada como zero em silêncio.

    A coerção custava uma dependência inteira na direção errada: `review/`, que
    é a camada `human`, tinha de importar a taxonomia de CONCILIAÇÃO para
    desserializar a fila. Uma proposta de qualquer outro domínio passando por
    ali levantaria `ValueError` num vocabulário que não é o dela.

    Quem compara passou a comparar por valor (`metrics.evaluate`), e aí a
    coerção deixou de ser necessária: `DivergenceType` é `StrEnum`, então o
    `str` que volta do JSON compara igual ao membro do enum. O que este teste
    protege agora é isso — o valor sobrevive à ida e volta, e continua casando
    com a taxonomia do domínio **sem** que a fronteira precise conhecê-la.
    """
    bruto = {
        "divergence_id": "d-b-b1",
        "tipo": "RETENCAO_IMPOSTO",
        "explicacao": "retenção de ISS",
        "evidencia": ["l1"],
        "confianca": "ALTA",
        "acao_sugerida": "conciliar_com(l1)",
        "cost": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "cache_creation_tokens": 0,
            "calls": 0,
        },
        "trace": [],
    }

    p = proposta_de_dict(bruto)

    assert p.tipo == DivergenceType.RETENCAO_IMPOSTO
    # E a fronteira não coage: o que volta é o `str` do JSON. Afirmar isso é o
    # que impede alguém de "consertar" o teste acima reintroduzindo o import da
    # taxonomia em `review/`.
    assert type(p.tipo) is str
