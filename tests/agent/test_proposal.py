import pytest

from orchestrator.agent.proposal import (
    Confidence,
    Cost,
    InvestigationOutput,
    Proposal,
    TraceEvent,
)
from orchestrator.taxonomy import DivergenceType


def _custo() -> Cost:
    return Cost(input_tokens=1000, output_tokens=200, cached_tokens=500, calls=2)


def test_custo_soma_tokens_ao_preco_do_modelo():
    # opus-5: 500 micro-cents por token de entrada, 2500 de saída, 50 de cache.
    c = _custo()
    assert c.microcents("claude-opus-5") == 1000 * 500 + 200 * 2500 + 500 * 50


def test_custo_de_modelo_mais_barato_e_menor():
    c = _custo()
    assert c.microcents("claude-haiku-4-5") < c.microcents("claude-opus-5")


def test_custo_rejeita_modelo_desconhecido():
    with pytest.raises(ValueError):
        _custo().microcents("modelo-que-nao-existe")


def test_custo_zero_e_neutro_na_soma():
    c = _custo()
    assert c + Cost.zero() == c


def test_custos_somam_campo_a_campo():
    soma = _custo() + _custo()
    assert soma.input_tokens == 2000
    assert soma.calls == 4


def test_proposta_carrega_evidencia_e_confianca():
    p = Proposal(
        divergence_id="d-b-b00001",
        tipo=DivergenceType.RETENCAO_IMPOSTO,
        explicacao="ISS de 5% retido na fonte",
        evidencia=["l00001: bruto 254925", "b00001: líquido 242179"],
        confianca=Confidence.ALTA,
        acao_sugerida="conciliar_com:l00001",
        cost=_custo(),
    )
    assert p.confianca is Confidence.ALTA
    assert len(p.evidencia) == 2


def test_abstencao_e_proposta_valida():
    p = Proposal.abstencao(divergence_id="d-b-b00002", motivo="sem contexto suficiente")
    assert p.tipo is DivergenceType.NAO_IDENTIFICADO
    assert p.confianca is Confidence.BAIXA
    assert p.acao_sugerida == "investigar_manual"


def test_confianca_vinda_como_string_e_coagida_ao_enum():
    # O plano 3 vai desserializar propostas; sem coerção, uma string crua
    # contornaria o guard de evidência e toda verificação por identidade.
    p = Proposal(
        divergence_id="d1",
        tipo="RETENCAO_IMPOSTO",
        explicacao="x",
        evidencia=["l1"],
        confianca="ALTA",
        acao_sugerida="conciliar",
        cost=Cost.zero(),
    )
    assert p.confianca is Confidence.ALTA
    assert p.tipo is DivergenceType.RETENCAO_IMPOSTO


def test_confianca_alta_como_string_tambem_exige_evidencia():
    with pytest.raises(ValueError):
        Proposal(
            divergence_id="d1",
            tipo="RETENCAO_IMPOSTO",
            explicacao="x",
            evidencia=[],
            confianca="ALTA",
            acao_sugerida="conciliar",
            cost=Cost.zero(),
        )


def test_proposta_com_confianca_alta_exige_evidencia():
    # Afirmar com confiança e sem evidência é exatamente o que destrói a
    # credibilidade do produto.
    with pytest.raises(ValueError):
        Proposal(
            divergence_id="d1",
            tipo=DivergenceType.RETENCAO_IMPOSTO,
            explicacao="acho que é retenção",
            evidencia=[],
            confianca=Confidence.ALTA,
            acao_sugerida="conciliar_com:l1",
            cost=Cost.zero(),
        )


def test_proposta_carrega_trace_auditavel():
    p = Proposal.abstencao(
        "d1", "x", trace=[TraceEvent(kind="llm", detail={"turno": 1, "tokens": 50})]
    )
    assert p.trace[0].kind == "llm"
    assert p.trace[0].detail["turno"] == 1


def test_proposta_sem_trace_nasce_com_lista_vazia():
    assert Proposal.abstencao("d1", "x").trace == []


def test_saida_de_investigacao_agrega_custo():
    p1 = Proposal.abstencao("d1", "x")
    p2 = Proposal.abstencao("d2", "y")
    out = InvestigationOutput(proposals=[p1, p2], cost=_custo() + _custo())
    assert out.cost.calls == 4
    assert len(out.proposals) == 2
